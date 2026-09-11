"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import {
  Background,
  BackgroundVariant,
  Controls,
  ReactFlow,
  applyEdgeChanges,
  applyNodeChanges,
  type Edge,
  type EdgeChange,
  type EdgeTypes,
  type Node,
  type NodeChange,
  type NodeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { useTheme } from "@/components/theme";
import { tokens } from "@/lib/stylex/tokens.stylex";
import type { NodeSpec } from "@/lib/api";
import {
  edgeTypes as productEdgeTypes,
  nodeTypes as productNodeTypes,
} from "@/features/workbench/canvas/WorkflowCanvas";
import { encodeHandleId } from "@/features/workbench/canvas/handles";
import {
  createWorkflowInputPlug,
  inputPlugsForPort,
} from "@/features/workbench/canvas/input-plugs";
import {
  DEFAULT_CANVAS_GRID_SETTINGS,
  shouldSnapPosition,
  snapPosition,
} from "@/features/workbench/canvas/grid-layout";
import {
  WORKFLOW_EDGE_TYPE,
  WORKFLOW_NODE_TYPE,
  createWorkflowNodeData,
  portMetaForPort,
  type WorkflowEdgeData,
  type WorkflowNodeData,
} from "@/features/workbench/canvas/types";
import { WorkspaceContextScope } from "@/features/workspaces/WorkspaceLayout";
import {
  IMPORT_TABLE_SPEC,
  RENDER_PAGE_SPEC,
  SUMMARIZE_TABLES_SPEC,
  sandboxWorkspaceContext,
} from "../../fixtures/drawer";

/**
 * The product canvas with real node cards, so the input plugs on screen are the
 * plugs that ship.
 *
 * This is a base, not a demo. It exists so a follow-up round can build an
 * interaction against real cards without first standing up a workspace, a
 * registry and a saved document.
 */
type CardNode = Node<WorkflowNodeData, typeof WORKFLOW_NODE_TYPE>;
type SpikeNode = CardNode;
type SpikeEdge = Edge<WorkflowEdgeData, typeof WORKFLOW_EDGE_TYPE>;

const nodeTypes = { ...productNodeTypes } as NodeTypes;

/** The handle the real card publishes for one input plug. */
function plugHandleId(
  data: WorkflowNodeData,
  port: WorkflowNodeData["spec"]["inputs"][number],
  plugId: string,
): string {
  return encodeHandleId(
    portMetaForPort(port, port.shape, plugId, data.artifactTypeBindings),
  );
}

/** The handle the real card publishes for a plain port. */
function portHandleId(
  port: WorkflowNodeData["spec"]["outputs"][number],
): string {
  return encodeHandleId(portMetaForPort(port));
}

/**
 * Stable plug ids, so the server and the client render the same rows. The
 * product reads saved plugs from the graph document; this sandbox has no
 * document, so it names them here instead of letting them be minted per render.
 */
const SANDBOX_PLUGS = {
  import: [{ id: "sandbox-seed-import-file", port: "file" }],
  summarize: [{ id: "sandbox-seed-summarize-tables", port: "tables" }],
  render: [{ id: "sandbox-seed-render-body", port: "body" }],
} as const;

function cardNode(
  id: keyof typeof SANDBOX_PLUGS,
  spec: NodeSpec,
  position: { x: number; y: number },
): CardNode {
  return {
    id,
    type: WORKFLOW_NODE_TYPE,
    position,
    selected: false,
    data: createWorkflowNodeData(spec, SANDBOX_PLUGS[id]),
  };
}

function initialState(): { nodes: SpikeNode[]; edges: SpikeEdge[] } {
  const nodes: SpikeNode[] = [
    cardNode("import", IMPORT_TABLE_SPEC, { x: 20, y: 40 }),
    cardNode("summarize", SUMMARIZE_TABLES_SPEC, { x: 20, y: 300 }),
    cardNode("render", RENDER_PAGE_SPEC, { x: 440, y: 170 }),
  ];
  const summarize = nodes.find((node) => node.id === "summarize");
  const render = nodes.find((node) => node.id === "render");
  const report = summarize?.data.spec.outputs[0];
  const body = render?.data.spec.inputs.find((port) => port.name === "body");
  const bodyPlug = render
    ? inputPlugsForPort(render.data.inputPlugs, "body")[0]
    : undefined;
  if (!summarize || !render || !report || !body || !bodyPlug) {
    return { nodes, edges: [] };
  }
  // The wire names a plug, not the bare port, which is how the product binds an
  // input that carries instance plugs.
  return {
    nodes,
    edges: [
      {
        id: "edge-report-body",
        type: WORKFLOW_EDGE_TYPE,
        source: "summarize",
        target: "render",
        sourceHandle: portHandleId(report),
        targetHandle: plugHandleId(render.data, body, bodyPlug.id),
        data: { enabled: true, collectionMode: "direct" },
      } satisfies SpikeEdge,
    ],
  };
}

/** One boot graph per page load, so the plug ids in the edge match the cards. */
let boot: { nodes: SpikeNode[]; edges: SpikeEdge[] } | null = null;

function bootState(): { nodes: SpikeNode[]; edges: SpikeEdge[] } {
  boot ??= initialState();
  return boot;
}

const s = stylex.create({
  canvas: {
    width: "100%",
    height: "100svh",
    backgroundColor: tokens.colorBg,
    color: tokens.colorText,
  },
});

export function DrawerInteractionSpike() {
  const { resolved } = useTheme();
  const [nodes, setNodes] = React.useState<SpikeNode[]>(
    () => bootState().nodes,
  );
  const [edges, setEdges] = React.useState<SpikeEdge[]>(
    () => bootState().edges,
  );

  const onNodesChange = React.useCallback(
    (changes: NodeChange<SpikeNode>[]) => {
      const settled = changes.map((change) => {
        if (
          change.type === "position" &&
          change.position &&
          shouldSnapPosition(DEFAULT_CANVAS_GRID_SETTINGS, {
            dragging: change.dragging === true,
            bypass: false,
          })
        ) {
          return {
            ...change,
            position: snapPosition(
              change.position,
              DEFAULT_CANVAS_GRID_SETTINGS.cellSize,
            ),
          };
        }
        return change;
      });
      setNodes((current) => applyNodeChanges(settled, current));
    },
    [],
  );

  const onEdgesChange = React.useCallback(
    (changes: EdgeChange<SpikeEdge>[]) => {
      setEdges((current) => applyEdgeChanges(changes, current));
    },
    [],
  );

  /** The card's own Add input button. Adds an empty plug, like the product. */
  const addPlugRow = React.useCallback((nodeId: string, portName: string) => {
    setNodes((current) =>
      current.map((node) =>
        node.id === nodeId
          ? {
              ...node,
              data: {
                ...node.data,
                inputPlugs: [
                  ...node.data.inputPlugs,
                  createWorkflowInputPlug(portName),
                ],
              },
            }
          : node,
      ),
    );
  }, []);

  const removePlugRow = React.useCallback((nodeId: string, plugId: string) => {
    setNodes((current) =>
      current.map((node) => {
        if (node.id !== nodeId) return node;
        const inputPlugBindings = Object.fromEntries(
          Object.entries(node.data.inputPlugBindings).filter(
            ([id]) => id !== plugId,
          ),
        );
        return {
          ...node,
          data: {
            ...node.data,
            inputPlugs: node.data.inputPlugs.filter(
              (plug) => plug.id !== plugId,
            ),
            inputPlugBindings,
          },
        };
      }),
    );
  }, []);

  const canvasNodes = React.useMemo(
    () =>
      nodes.map((node) => ({
        ...node,
        data: {
          ...node.data,
          onAddInputPlug: addPlugRow,
          onRemoveInputPlug: removePlugRow,
        },
      })),
    [addPlugRow, nodes, removePlugRow],
  );

  return (
    <WorkspaceContextScope value={sandboxWorkspaceContext()}>
      <div {...stylex.props(s.canvas)}>
        <ReactFlow<SpikeNode, SpikeEdge>
          nodes={canvasNodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={productEdgeTypes as EdgeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onPaneClick={() =>
            setNodes((current) =>
              current.map((node) => ({ ...node, selected: false })),
            )
          }
          fitView
          fitViewOptions={{ padding: 0.25, maxZoom: 0.85 }}
          minZoom={0.3}
          maxZoom={1.6}
          colorMode={resolved}
          connectOnClick={false}
          panOnScroll
          panOnDrag={[1, 2]}
          selectionOnDrag
          proOptions={{ hideAttribution: true }}
        >
          <Background
            variant={BackgroundVariant.Lines}
            gap={DEFAULT_CANVAS_GRID_SETTINGS.cellSize}
            offset={DEFAULT_CANVAS_GRID_SETTINGS.cellSize / 2}
            lineWidth={1}
            color={tokens.colorGrid}
          />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
    </WorkspaceContextScope>
  );
}
