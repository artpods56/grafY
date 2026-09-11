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
import type { NodeSpec, Port } from "@/lib/api";
import {
  edgeTypes as productEdgeTypes,
  nodeTypes as productNodeTypes,
} from "@/features/workbench/canvas/WorkflowCanvas";
import {
  connectionArtifactContractIsValid,
  decodeHandleId,
  encodeHandleId,
} from "@/features/workbench/canvas/handles";
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
  SANDBOX_ARTIFACTS,
  SUMMARIZE_TABLES_SPEC,
  sandboxWorkspaceContext,
  type SandboxArtifact,
} from "../../fixtures/drawer";

/**
 * A real canvas with real node cards, so the plugs under test are the plugs
 * that ship. Everything else about the drawer interaction was cut, and what
 * remains is the part a follow-up round needs: a card whose input rows carry
 * live plug identity, and a drag that can find the plug under the pointer.
 */
type CardNode = Node<WorkflowNodeData, typeof WORKFLOW_NODE_TYPE>;
type SpikeNode = CardNode;
type SpikeEdge = Edge<WorkflowEdgeData, typeof WORKFLOW_EDGE_TYPE>;

const nodeTypes = { ...productNodeTypes } as NodeTypes;

function artifactById(id: string): SandboxArtifact | undefined {
  return SANDBOX_ARTIFACTS.find((artifact) => artifact.id === id);
}

function portTypeLabel(port: Port): string {
  if (!port.artifact_type) return "any";
  return `${port.artifact_type.id}@${port.artifact_type.schema_version}`;
}

/** The handle the real card publishes for one input plug. */
function plugHandleId(
  data: WorkflowNodeData,
  port: Port,
  plugId: string,
): string {
  return encodeHandleId(
    portMetaForPort(port, port.shape, plugId, data.artifactTypeBindings),
  );
}

/** The handle the real card publishes for a plain port. */
function portHandleId(port: Port): string {
  return encodeHandleId(portMetaForPort(port));
}

/** The artifact described as a source port, so the drop check can compare it. */
function artifactPort(artifact: SandboxArtifact): Port {
  return {
    name: "dropped",
    title: "dropped",
    description: null,
    direction: "output",
    artifact_type: {
      id: artifact.artifactType,
      schema_version: artifact.schemaVersion,
    },
    artifact_type_variable: null,
    shape: "one",
    accepted_shapes: ["one"],
    instance_plugs: false,
    variadic: false,
    required: false,
  };
}

/** True when this artifact may satisfy this input port. */
function artifactSatisfies(
  artifact: SandboxArtifact,
  handleId: string,
): boolean {
  return connectionArtifactContractIsValid({
    sourceHandle: encodeHandleId(portMetaForPort(artifactPort(artifact))),
    targetHandle: handleId,
  });
}

type DropOutcome =
  | { ok: false; reason: string }
  | { ok: true; data: WorkflowNodeData; sequenceLength: number };

/**
 * Satisfy one input with an artifact.
 *
 * A `one` port keeps a single origin, so a second artifact replaces the first on
 * the same row. A `many` port holds a sequence, so a drop on a row that already
 * holds an artifact appends a new row instead of overwriting it.
 */
function withSatisfiedPlug(
  data: WorkflowNodeData,
  portName: string,
  plugId: string | undefined,
  label: string,
  newPlugId: string,
): DropOutcome {
  const port = data.spec.inputs.find(
    (candidate) => candidate.name === portName,
  );
  if (!port) return { ok: false, reason: `no port named ${portName}` };
  const many = port.shape === "many" || port.accepted_shapes.includes("many");
  const isBound = (id: string) => Boolean(data.inputPlugBindings[id]);
  const inputPlugs = [...data.inputPlugs];

  let target = plugId
    ? inputPlugs.find((plug) => plug.id === plugId)
    : undefined;
  if (target && many && isBound(target.id)) target = undefined;
  target ??= inputPlugs.find(
    (plug) => plug.portName === portName && !isBound(plug.id),
  );
  if (!target) {
    target = { id: newPlugId, portName };
    inputPlugs.push(target);
  }

  return {
    ok: true,
    sequenceLength:
      inputPlugs.filter(
        (plug) => plug.portName === portName && isBound(plug.id),
      ).length + 1,
    data: {
      ...data,
      inputPlugs,
      inputPlugBindings: {
        ...data.inputPlugBindings,
        [target.id]: {
          sourceLabel: label,
          sourceShape: many ? "many" : "one",
        },
      },
    },
  };
}

/**
 * Stable plug ids, so the server and the client render the same rows. The
 * product reads saved plugs from the graph document; a sandbox has no document,
 * so it names them here instead of letting them be minted per render.
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

/** One boot graph per page load, so plug ids in the edge match the plugs on the cards. */
let boot: { nodes: SpikeNode[]; edges: SpikeEdge[] } | null = null;

function bootState(): { nodes: SpikeNode[]; edges: SpikeEdge[] } {
  boot ??= initialState();
  return boot;
}

const s = stylex.create({
  page: {
    position: "relative",
    width: "100%",
    height: "100svh",
    overflow: "hidden",
    backgroundColor: tokens.colorBg,
    color: tokens.colorText,
  },
  canvas: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
  },
  tray: {
    position: "absolute",
    top: "12px",
    left: "12px",
    zIndex: 5,
    display: "flex",
    flexDirection: "column",
    alignItems: "flex-start",
    gap: "6px",
    padding: "8px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusSm,
    backgroundColor: tokens.colorChrome,
  },
  trayTitle: {
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
  },
  chip: {
    display: "flex",
    alignItems: "baseline",
    gap: "6px",
    padding: "4px 8px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusSm,
    backgroundColor: tokens.colorSurface,
    color: tokens.colorText,
    cursor: "grab",
    fontSize: tokens.fontSizeXs,
  },
  chipType: {
    color: tokens.colorMuted,
  },
  status: {
    position: "absolute",
    left: "12px",
    bottom: "12px",
    zIndex: 5,
    maxWidth: "620px",
    padding: "6px 10px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusSm,
    backgroundColor: tokens.colorChrome,
    color: tokens.colorText,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
  },
});

interface PlugTarget {
  node: CardNode;
  port: Port;
  plugId: string | undefined;
  handleId: string;
}

export function DrawerInteractionSpike() {
  const { resolved } = useTheme();
  const [nodes, setNodes] = React.useState<SpikeNode[]>(
    () => bootState().nodes,
  );
  // The drop path reads the graph as it is at drop time. A drag captures its
  // node list at drag start, and a second drop would otherwise see the first
  // drop's stale bindings and reuse its row.
  const nodesRef = React.useRef(nodes);
  React.useEffect(() => {
    nodesRef.current = nodes;
  }, [nodes]);
  const [edges, setEdges] = React.useState<SpikeEdge[]>(
    () => bootState().edges,
  );
  const [status, setStatus] = React.useState(
    "Drag a chip onto an input plug. A filled row turns its handle square.",
  );
  // Browsers hide `dataTransfer` contents during `dragover`, so the drag source
  // is carried in a ref and only read out of the event at drop time.
  const draggingRef = React.useRef<string | null>(null);

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

  /**
   * Answer a drop by satisfying one input plug. A `many` port grows a new row
   * when the dropped row already holds an artifact; a `one` port keeps a single
   * origin on its row. A live wire on that port is disabled, never removed.
   */
  const satisfyPlug = React.useCallback(
    (
      nodeId: string,
      portName: string,
      plugId: string | undefined,
      label: string,
    ): DropOutcome => {
      const node = nodesRef.current.find(
        (candidate) => candidate.id === nodeId,
      );
      if (!node) return { ok: false, reason: "unknown node" };
      const outcome = withSatisfiedPlug(
        node.data,
        portName,
        plugId,
        label,
        // Rows are dropped client-side only, but a React StrictMode double
        // render would otherwise mint two ids for one row. Count rows, not time.
        `sandbox-${nodeId}-${portName}-${node.data.inputPlugs.length}`,
      );
      if (!outcome.ok) return outcome;
      setNodes((current) =>
        current.map((candidate) =>
          candidate.id === nodeId
            ? { ...candidate, data: outcome.data }
            : candidate,
        ),
      );
      return outcome;
    },
    [],
  );

  /**
   * Resolve which input the pointer is over by hit testing the real React Flow
   * handles. Reading the topmost element would fail, because the edge component
   * renders a bend-handle layer above the node cards.
   *
   * A plug mark is a small target, so a pointer that sits anywhere inside a plug
   * row resolves to that row's own mark.
   */
  const plugUnder = React.useCallback(
    (clientX: number, clientY: number): PlugTarget | null => {
      const resolve = (handle: HTMLElement): PlugTarget | null => {
        const raw = handle.getAttribute("data-handleid");
        const decoded = decodeHandleId(raw);
        if (!decoded || decoded.direction !== "input") return null;
        const node = nodesRef.current.find(
          (candidate) => candidate.id === handle.dataset.nodeid,
        );
        if (!node) return null;
        const port = node.data.spec.inputs.find(
          (candidate) => candidate.name === decoded.portName,
        );
        if (!port) return null;
        // React Flow writes `data-handleid` once, at mount, so it goes stale
        // when the plug on that row is replaced. The row element is the live
        // identity.
        const rowPlugId = handle.closest<HTMLElement>("[data-input-plug-id]")
          ?.dataset.inputPlugId;
        return {
          node,
          port,
          plugId: rowPlugId ?? decoded.plugId,
          handleId: raw ?? "",
        };
      };

      let best: { handle: HTMLElement; distance: number } | null = null;
      for (const handle of document.querySelectorAll<HTMLElement>(
        ".react-flow__handle",
      )) {
        const rect = handle.getBoundingClientRect();
        const distance = Math.hypot(
          clientX - (rect.x + rect.width / 2),
          clientY - (rect.y + rect.height / 2),
        );
        if (distance > Math.max(rect.width, rect.height) / 2 + 10) continue;
        if (!best || distance < best.distance) best = { handle, distance };
      }
      const onMark = best ? resolve(best.handle) : null;
      if (onMark) return onMark;

      for (const row of document.querySelectorAll<HTMLElement>(
        "[data-input-plug-id]",
      )) {
        const rect = row.getBoundingClientRect();
        const inside =
          clientX >= rect.left &&
          clientX <= rect.right &&
          clientY >= rect.top &&
          clientY <= rect.bottom;
        if (!inside) continue;
        const handle = row.querySelector<HTMLElement>(".react-flow__handle");
        const onRow = handle ? resolve(handle) : null;
        if (onRow) return onRow;
      }
      return null;
    },
    [],
  );

  const onDragOver = React.useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      const artifactId = draggingRef.current;
      const artifact = artifactId ? artifactById(artifactId) : undefined;
      const plug = plugUnder(event.clientX, event.clientY);
      if (!artifact || !plug) return;
      setStatus(
        artifactSatisfies(artifact, plug.handleId)
          ? `Release to satisfy ${plug.port.name}.`
          : `This input accepts ${portTypeLabel(plug.port)}, not ${artifact.artifactType}@${artifact.schemaVersion}.`,
      );
    },
    [plugUnder],
  );

  const onDrop = React.useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      const artifactId =
        event.dataTransfer.getData("text/plain") || draggingRef.current;
      draggingRef.current = null;
      const artifact = artifactId ? artifactById(artifactId) : undefined;
      if (!artifact) return;
      const plug = plugUnder(event.clientX, event.clientY);
      if (!plug) {
        setStatus(`${artifact.label} needs an input plug. Nothing was placed.`);
        return;
      }
      if (!artifactSatisfies(artifact, plug.handleId)) {
        setStatus(
          `Refused. ${artifact.artifactType}@${artifact.schemaVersion} cannot satisfy ${plug.port.name}, which accepts ${portTypeLabel(plug.port)}.`,
        );
        return;
      }

      const { node, port, plugId } = plug;
      const plugs = inputPlugsForPort(node.data.inputPlugs, port.name);
      const targetPlug = plugId ?? plugs[0]?.id;
      const many =
        port.shape === "many" || port.accepted_shapes.includes("many");

      if (many) {
        const bound = plugs.filter(
          (plug) => node.data.inputPlugBindings[plug.id],
        ).length;
        const outcome = satisfyPlug(
          node.id,
          port.name,
          targetPlug,
          artifact.label,
        );
        if (!outcome.ok) return;
        setStatus(
          `${artifact.label} added to ${port.name}. The input holds ${bound + 1} artifacts as one sequence, in plug order.`,
        );
        return;
      }

      const held = targetPlug
        ? node.data.inputPlugBindings[targetPlug]?.sourceLabel
        : undefined;
      const incoming = edges.find(
        (edge) =>
          edge.target === node.id &&
          edge.data?.enabled !== false &&
          decodeHandleId(edge.targetHandle)?.portName === port.name,
      );
      const outgoing = nodes.find((candidate) => candidate.id === node.id);
      if (!outgoing) return;

      satisfyPlug(node.id, port.name, targetPlug, artifact.label);
      if (incoming) {
        setEdges((current) =>
          current.map((edge) =>
            edge.id === incoming.id
              ? {
                  ...edge,
                  data: {
                    ...edge.data,
                    enabled: false,
                    collectionMode: edge.data?.collectionMode ?? "direct",
                  },
                }
              : edge,
          ),
        );
        setStatus(
          `${artifact.label} replaced the wire on ${port.name}. The wire stays in the graph disabled, so the swap is one undo.`,
        );
        return;
      }
      setStatus(
        held
          ? `${artifact.label} replaced the origin ${held} on ${port.name}.`
          : `${artifact.label} now satisfies ${port.name} as an origin. No node was added and nothing was copied.`,
      );
    },
    [edges, nodes, plugUnder, satisfyPlug],
  );

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
      <div {...stylex.props(s.page)}>
        <div
          {...stylex.props(s.canvas)}
          onDragOver={onDragOver}
          onDrop={onDrop}
        >
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

        <div {...stylex.props(s.tray)}>
          <span {...stylex.props(s.trayTitle)}>Artifacts</span>
          {SANDBOX_ARTIFACTS.map((artifact) => (
            <div
              key={artifact.id}
              draggable
              data-artifact-id={artifact.id}
              onDragStart={(event) => {
                draggingRef.current = artifact.id;
                event.dataTransfer.setData("text/plain", artifact.id);
                event.dataTransfer.effectAllowed = "copy";
              }}
              {...stylex.props(s.chip)}
            >
              <span>{artifact.label}</span>
              <span {...stylex.props(s.chipType)}>{artifact.artifactType}</span>
            </div>
          ))}
        </div>

        <div data-spike-status {...stylex.props(s.status)}>
          {status}
        </div>
      </div>
    </WorkspaceContextScope>
  );
}
