"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  NodeResizer,
  Position,
  ReactFlow,
  applyEdgeChanges,
  applyNodeChanges,
  type Edge,
  type EdgeChange,
  type EdgeTypes,
  type Node,
  type NodeChange,
  type NodeProps,
  type NodeTypes,
  type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { useTheme } from "@/components/theme";
import { tokens } from "@/lib/stylex/tokens.stylex";
import type { NodeSpec, Port } from "@/lib/api";
import { edgeTypes as productEdgeTypes } from "@/features/workbench/canvas/WorkflowCanvas";
import {
  connectionArtifactContractIsValid,
  decodeHandleId,
  encodeHandleId,
} from "@/features/workbench/canvas/handles";
import {
  CanvasNodeHeader,
  CanvasPortRail,
  CanvasPortTab,
} from "@/features/workbench/canvas/nodes/CanvasNodeChrome";
import { artifactTypeColor } from "@/features/workbench/canvas/nodes.css";
import {
  WORKFLOW_EDGE_TYPE,
  type WorkflowEdgeData,
} from "@/features/workbench/canvas/types";
import { SandboxShell } from "../../SandboxShell";
import {
  DRAWER_ARTIFACTS,
  IMPORT_TABLE_SPEC,
  KEPT_ARTIFACTS,
  PRODUCED_ARTIFACTS,
  RENDER_PAGE_SPEC,
  SUMMARIZE_TABLES_SPEC,
  type DrawerArtifact,
} from "../../fixtures/drawer";

const CARD_NODE_TYPE = "sandboxDrawerCard";
const DISPLAY_NODE_TYPE = "sandboxArtifactDisplay";

const VARIANTS = [
  {
    id: "replace",
    label: "Replace what is there",
    note: "Drop on a satisfied input: the origin replaces the old one, and a conflicting wire stays in the graph disabled.",
  },
  {
    id: "refuse",
    label: "Refuse the drop",
    note: "Drop on a satisfied input: nothing changes, and the refusal names what holds the input.",
  },
] as const;

type VariantId = (typeof VARIANTS)[number]["id"];

interface CardData extends Record<string, unknown> {
  spec: NodeSpec;
  /** Plug id to the artifact label that satisfies it. */
  bindings: Record<string, string>;
  /** Port name to its plug ids, in sequence order. */
  plugs: Record<string, string[]>;
}

interface ArtifactDisplayData extends Record<string, unknown> {
  artifactId: string;
}

type CardNode = Node<CardData, typeof CARD_NODE_TYPE>;
type DisplayNode = Node<ArtifactDisplayData, typeof DISPLAY_NODE_TYPE>;
type SpikeNode = CardNode | DisplayNode;
type SpikeEdge = Edge<WorkflowEdgeData, typeof WORKFLOW_EDGE_TYPE>;

let plugSeq = 0;

function newPlugId(portName: string): string {
  plugSeq += 1;
  return `${portName}-plug-${plugSeq}`;
}

function artifactById(id: string): DrawerArtifact | undefined {
  return DRAWER_ARTIFACTS.find((artifact) => artifact.id === id);
}

function portColor(port: Port): string {
  const id = port.artifact_type?.id;
  return artifactTypeColor(id ?? "", tokens.colorAccent);
}

function portTypeLabel(port: Port): string {
  if (!port.artifact_type) return "any";
  return `${port.artifact_type.id}@${port.artifact_type.schema_version}`;
}

function handleIdFor(
  port: Port,
  plugId: string | undefined,
  direction: "input" | "output",
): string {
  return encodeHandleId({
    portName: port.name,
    artifactTypeId: port.artifact_type?.id ?? "unknown",
    schemaVersion: port.artifact_type?.schema_version ?? 1,
    shape: port.shape,
    direction,
    ...(plugId ? { plugId } : {}),
  });
}

function DrawerCardNode({ id, data, selected }: NodeProps<CardNode>) {
  const inputRows = React.useMemo(() => {
    const rows: { port: Port; plugId: string }[] = [];
    for (const port of data.spec.inputs) {
      const plugs = data.plugs[port.name]?.length
        ? data.plugs[port.name]
        : [newPlugId(port.name)];
      for (const plugId of plugs) rows.push({ port, plugId });
    }
    return rows;
  }, [data.plugs, data.spec.inputs]);

  const rowCount = Math.max(
    inputRows.length,
    data.spec.outputs.length,
    1,
  );

  const rows = Array.from({ length: rowCount }, (_, index) => {
    const input = inputRows[index];
    const output = data.spec.outputs[index];
    return {
      input: input ? (
        <PortSlot
          nodeId={id}
          port={input.port}
          plugId={input.plugId}
          binding={data.bindings[input.plugId]}
          sequenceIndex={
            data.plugs[input.port.name]?.length > 1 ? index + 1 : null
          }
          sequenceLength={data.plugs[input.port.name]?.length ?? 0}
        />
      ) : undefined,
      output: output ? (
        <CanvasPortTab
          nodeId={id}
          direction="output"
          label={output.name}
          hint={output.shape === "many" ? "many" : undefined}
          handleId={handleIdFor(output, undefined, "output")}
          color={portColor(output)}
          isConnectable
          ariaLabel={`${output.name} output, ${portTypeLabel(output)}`}
        />
      ) : undefined,
    };
  });

  return (
    <div
      {...stylex.props(
        s.card,
        selected ? s.cardSelected : null,
      )}
      data-testid="drawer-card"
    >
      <CanvasNodeHeader
        title={data.spec.title}
        selected={selected}
        aboutLabel={`About ${data.spec.title}`}
        aboutTitle={data.spec.title}
        aboutDescription={data.spec.description ?? ""}
      >
        <span {...stylex.props(s.cardFlag)} />
      </CanvasNodeHeader>
      <CanvasPortRail rows={rows} />
    </div>
  );
}

function PortSlot({
  nodeId,
  port,
  plugId,
  binding,
  sequenceIndex,
  sequenceLength,
}: {
  nodeId: string;
  port: Port;
  plugId: string;
  binding: string | undefined;
  sequenceIndex: number | null;
  sequenceLength: number;
}) {
  return (
    <div {...stylex.props(s.plugSlot)}>
      <CanvasPortTab
        nodeId={nodeId}
        direction="input"
        label={port.name}
        hint={port.shape === "many" ? "many" : undefined}
        handleId={handleIdFor(port, plugId, "input")}
        color={portColor(port)}
        isConnectable
        ariaLabel={`${port.name} input, ${portTypeLabel(port)}`}
      />
      {binding ? (
        <span
          {...stylex.props(s.originChip)}
          data-origin-for={plugId}
          title={`Satisfied by the artifact ${binding}`}
        >
          {sequenceIndex ? (
            <span {...stylex.props(s.originIndex)}>{sequenceIndex}</span>
          ) : null}
          <span {...stylex.props(s.originLabel)}>{binding}</span>
        </span>
      ) : (
        <span {...stylex.props(s.emptyChip)}>Connect input</span>
      )}
      {sequenceLength > 1 ? (
        <span {...stylex.props(s.sequenceNote)}>
          {sequenceLength} in sequence
        </span>
      ) : null}
    </div>
  );
}

function ArtifactDisplayNode({ data, selected }: NodeProps<DisplayNode>) {
  const artifact = artifactById(data.artifactId);
  if (!artifact) return null;

  return (
    <div {...stylex.props(s.display, selected ? s.displaySelected : null)}>
      <NodeResizer minWidth={56} minHeight={56} isVisible={selected} />
      <Handle
        type="source"
        position={Position.Right}
        id={handleIdFor(placedPort(artifact), undefined, "output")}
        style={handleStyleAt(10, tokens.colorAccent)}
      />
      <span {...stylex.props(s.displayMeta)}>
        {artifact.label} · {artifact.artifactType}@{artifact.schemaVersion}
      </span>
      <ArtifactBody artifact={artifact} />
    </div>
  );
}

function placedPort(artifact: DrawerArtifact): Port {
  return {
    name: "placed",
    title: "placed",
    description: null,
    direction: "output",
    artifact_type: { id: artifact.artifactType, schema_version: artifact.schemaVersion },
    artifact_type_variable: null,
    shape: "one",
    accepted_shapes: ["one"],
    instance_plugs: false,
    variadic: false,
    required: false,
  };
}

function handleStyleAt(top: number, color: string) {
  const surface = tokens.colorSurface;
  return {
    top: `${top}px`,
    width: "14px",
    height: "14px",
    borderRadius: "9999px",
    background: `radial-gradient(circle, ${surface} 0 3px, ${color} 3px 5px, transparent 5.5px)`,
    border: "none",
    cursor: "crosshair",
  };
}

function artifactFamily(artifactType: string): "image" | "table" | "text" {
  if (artifactType.startsWith("file.png") || artifactType.startsWith("image.")) {
    return "image";
  }
  if (artifactType.startsWith("table.")) return "table";
  return "text";
}

function ArtifactBody({ artifact }: { artifact: DrawerArtifact }) {
  const family = artifactFamily(artifact.artifactType);
  if (family === "image") {
    return (
      <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice" width="100%" height="100%">
        <rect width="100" height="100" fill="#12212e" />
        <circle cx="68" cy="30" r="9" fill="#e6c07b" />
        <path d="M0 76 L30 52 L52 70 L74 46 L100 68 L100 100 L0 100 Z" fill="#3f6d59" />
        <path d="M0 88 L24 72 L48 86 L72 70 L100 84 L100 100 L0 100 Z" fill="#2c4c40" />
      </svg>
    );
  }
  if (family === "table") {
    return (
      <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice" width="100%" height="100%">
        <rect width="100" height="100" fill="#101a24" />
        <rect width="100" height="16" fill="#26405c" />
        {[26, 40, 54, 68, 82].map((y) => (
          <rect key={y} x="0" y={y} width="100" height="7" fill="#1b2a3a" />
        ))}
        {[22, 48, 74].map((x) => (
          <rect key={x} x={x} y="0" width="1" height="100" fill="#26405c" />
        ))}
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice" width="100%" height="100%">
      <rect width="100" height="100" fill="#101a24" />
      {[24, 38, 52, 66, 80].map((y, index) => (
        <rect
          key={y}
          x="14"
          y={y}
          width={index % 2 === 0 ? 62 : 44}
          height="5"
          rx="2"
          fill="#4d6a86"
        />
      ))}
    </svg>
  );
}

const nodeTypes = {
  [CARD_NODE_TYPE]: DrawerCardNode,
  [DISPLAY_NODE_TYPE]: ArtifactDisplayNode,
} as NodeTypes;

function initialPlugs(spec: NodeSpec): Record<string, string[]> {
  const plugs: Record<string, string[]> = {};
  for (const port of spec.inputs) {
    if (!port.instance_plugs) continue;
    plugs[port.name] = [newPlugId(port.name)];
  }
  return plugs;
}

function cardNode(
  id: string,
  spec: NodeSpec,
  position: { x: number; y: number },
): CardNode {
  return {
    id,
    type: CARD_NODE_TYPE,
    position,
    selected: false,
    data: { spec, bindings: {}, plugs: initialPlugs(spec) },
  };
}

function initialNodes(): SpikeNode[] {
  return [
    cardNode("import", IMPORT_TABLE_SPEC, { x: 20, y: 40 }),
    cardNode("summarize", SUMMARIZE_TABLES_SPEC, { x: 20, y: 290 }),
    cardNode("render", RENDER_PAGE_SPEC, { x: 400, y: 150 }),
  ];
}

function initialEdges(nodes: readonly SpikeNode[]): SpikeEdge[] {
  const summarize = nodes.find((node) => node.id === "summarize");
  const render = nodes.find((node) => node.id === "render");
  if (summarize?.type !== CARD_NODE_TYPE || render?.type !== CARD_NODE_TYPE) {
    return [];
  }
  const report = summarize.data.spec.outputs[0];
  const body = render.data.spec.inputs.find((port) => port.name === "body");
  const bodyPlug = render.data.plugs.body?.[0];
  if (!report || !body || !bodyPlug) return [];

  return [
    {
      id: "edge-report-body",
      type: WORKFLOW_EDGE_TYPE,
      source: "summarize",
      target: "render",
      sourceHandle: handleIdFor(report, undefined, "output"),
      targetHandle: handleIdFor(body, bodyPlug, "input"),
      data: { enabled: true, collectionMode: "direct" },
    } satisfies SpikeEdge,
  ];
}

function initialState(): { nodes: SpikeNode[]; edges: SpikeEdge[] } {
  const nodes = initialNodes();
  return { nodes, edges: initialEdges(nodes) };
}

/** One boot graph per page load, so plug ids in the edge match the plugs on the cards. */
let boot: { nodes: SpikeNode[]; edges: SpikeEdge[] } | null = null;

function bootState(): { nodes: SpikeNode[]; edges: SpikeEdge[] } {
  boot ??= initialState();
  return boot;
}

const s = stylex.create({
  card: {
    minWidth: "230px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorSurface,
    boxShadow: tokens.shadowNode,
    overflow: "hidden",
  },
  cardSelected: {
    borderColor: tokens.colorAccent,
  },
  cardFlag: {
    display: "inline-block",
    minWidth: "8px",
    height: "8px",
    borderRadius: "9999px",
    backgroundColor: "transparent",
  },
  plugSlot: {
    position: "relative",
    display: "flex",
    alignItems: "center",
    gap: "6px",
    minWidth: 0,
  },
  originChip: {
    display: "inline-flex",
    alignItems: "center",
    gap: "5px",
    height: "20px",
    maxWidth: "150px",
    paddingInline: "7px",
    borderRadius: "9999px",
    backgroundColor: tokens.colorSurfaceSunken,
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorAccent,
    color: tokens.colorText,
    fontSize: "10.5px",
    fontWeight: 600,
  },
  originIndex: {
    color: tokens.colorAccent,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
  },
  originLabel: {
    minWidth: 0,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  emptyChip: {
    color: tokens.colorMuted,
    fontSize: "10.5px",
    fontStyle: "italic",
    whiteSpace: "nowrap",
  },
  sequenceNote: {
    position: "absolute",
    left: "14px",
    top: "100%",
    color: tokens.colorMuted,
    fontSize: "9.5px",
    letterSpacing: "0.03em",
    textTransform: "uppercase",
    whiteSpace: "nowrap",
  },
  display: {
    position: "relative",
    width: "100%",
    height: "100%",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    overflow: "visible",
    outlineWidth: 1,
    outlineStyle: "solid",
    outlineColor: "transparent",
    cursor: "grab",
  },
  displaySelected: {
    outlineColor: tokens.colorAccent,
  },
  displayMeta: {
    position: "absolute",
    bottom: "100%",
    left: 0,
    marginBottom: "3px",
    color: tokens.colorMuted,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: "10px",
    whiteSpace: "nowrap",
    pointerEvents: "none",
  },
  workbench: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) 272px",
    height: "calc(100svh - 208px)",
    minHeight: "460px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusMd,
    overflow: "hidden",
    backgroundColor: tokens.colorBg,
  },
  canvasWrap: {
    position: "relative",
    minWidth: 0,
  },
  canvas: { width: "100%", height: "100%" },
  status: {
    position: "absolute",
    left: "12px",
    bottom: "12px",
    zIndex: 6,
    maxWidth: "min(600px, calc(100% - 24px))",
    padding: "7px 10px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusSm,
    backgroundColor: tokens.colorChrome,
    color: tokens.colorText,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.4,
  },
  statusBad: { borderColor: tokens.colorDanger, color: tokens.colorDanger },
  statusGood: { borderColor: tokens.colorAccent },
  hint: {
    position: "absolute",
    left: "12px",
    top: "12px",
    zIndex: 6,
    padding: "7px 10px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusSm,
    backgroundColor: tokens.colorChrome,
    color: tokens.colorText,
    fontSize: tokens.fontSizeXs,
    pointerEvents: "none",
  },
  drawer: {
    display: "grid",
    gridTemplateRows: "auto auto minmax(0, 1fr) auto",
    minHeight: 0,
    borderLeftWidth: 1,
    borderLeftStyle: "solid",
    borderLeftColor: tokens.colorBorder,
    backgroundColor: tokens.colorChrome,
  },
  tabs: { display: "flex", gap: "4px", padding: "8px 8px 0" },
  tab: {
    flex: 1,
    height: "28px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: "transparent",
    borderRadius: tokens.radiusSm,
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: tokens.colorMuted,
    cursor: "pointer",
    fontSize: tokens.fontSizeXs,
  },
  tabActive: {
    borderColor: tokens.colorBorder,
    backgroundColor: tokens.colorSurfaceSunken,
    color: tokens.colorText,
    fontWeight: 600,
  },
  drawerNote: {
    padding: "8px 10px 6px",
    color: tokens.colorMuted,
    fontSize: "10.5px",
    lineHeight: 1.45,
  },
  rows: {
    minHeight: 0,
    overflowY: "auto",
    padding: "0 8px 8px",
    display: "flex",
    flexDirection: "column",
    gap: "2px",
  },
  row: {
    display: "flex",
    alignItems: "center",
    gap: "7px",
    padding: "5px 6px",
    borderRadius: tokens.radiusSm,
    cursor: "grab",
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
  },
  swatch: { width: "3px", alignSelf: "stretch", borderRadius: "9999px" },
  rowLabel: {
    minWidth: 0,
    flex: 1,
    overflow: "hidden",
    color: tokens.colorText,
    fontSize: tokens.fontSizeXs,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  rowType: {
    color: tokens.colorMuted,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: "10px",
    whiteSpace: "nowrap",
  },
  stale: {
    padding: "0 5px",
    borderRadius: "9999px",
    backgroundColor: tokens.colorSurfaceSunken,
    color: tokens.colorWarning,
    fontSize: "9px",
    fontWeight: 600,
    letterSpacing: "0.04em",
  },
  smallButton: {
    height: "20px",
    paddingInline: "6px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusSm,
    backgroundColor: "transparent",
    color: tokens.colorMuted,
    cursor: "pointer",
    fontSize: "10px",
  },
  keepForm: { display: "flex", gap: "4px", padding: "5px 6px" },
  input: {
    minWidth: 0,
    flex: 1,
    height: "22px",
    paddingInline: "6px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusSm,
    backgroundColor: tokens.colorBg,
    color: tokens.colorText,
    fontSize: tokens.fontSizeXs,
  },
  drawerFoot: {
    padding: "8px 10px 10px",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorBorder,
    color: tokens.colorMuted,
    fontSize: "10.5px",
    lineHeight: 1.5,
  },
});

export function DrawerInteractionSpike() {
  const { resolved } = useTheme();
  const [variant, setVariant] = React.useState<VariantId>("replace");
  const [nodes, setNodes] = React.useState<SpikeNode[]>(() => bootState().nodes);
  const [edges, setEdges] = React.useState<SpikeEdge[]>(() => bootState().edges);
  const [kept, setKept] = React.useState<readonly DrawerArtifact[]>(KEPT_ARTIFACTS);
  const [tab, setTab] = React.useState<"produced" | "kept">("produced");
  const [naming, setNaming] = React.useState<{ id: string; value: string } | null>(null);
  const [status, setStatus] = React.useState<{ tone: "info" | "good" | "bad"; text: string }>({
    tone: "info",
    text: "Drag a row from the drawer onto a port row, or onto empty canvas.",
  });
  const [hover, setHover] = React.useState<{ text: string; ok: boolean } | null>(null);
  const draggingRef = React.useRef<string | null>(null);
  const instanceRef = React.useRef<ReactFlowInstance<SpikeNode, SpikeEdge> | null>(null);
  const produced = PRODUCED_ARTIFACTS;

  const onNodesChange = React.useCallback((changes: NodeChange<SpikeNode>[]) => {
    setNodes((current) => applyNodeChanges(changes, current));
  }, []);

  const onEdgesChange = React.useCallback((changes: EdgeChange<SpikeEdge>[]) => {
    setEdges((current) => applyEdgeChanges(changes, current));
  }, []);

  const setBinding = React.useCallback(
    (nodeId: string, plugId: string, label: string) => {
      setNodes((current) =>
        current.map((node) =>
          node.id === nodeId && node.type === CARD_NODE_TYPE
            ? {
                ...node,
                data: {
                  ...node.data,
                  bindings: { ...node.data.bindings, [plugId]: label },
                },
              }
            : node,
        ),
      );
    },
    [],
  );

  const addPlug = React.useCallback(
    (nodeId: string, portName: string, label: string) => {
      setNodes((current) =>
        current.map((node) => {
          if (node.id !== nodeId || node.type !== CARD_NODE_TYPE) return node;
          const plugs = node.data.plugs[portName] ?? [];
          const empty = plugs.find((plugId) => !node.data.bindings[plugId]);
          if (empty) {
            return {
              ...node,
              data: {
                ...node.data,
                bindings: { ...node.data.bindings, [empty]: label },
              },
            };
          }
          const appended = newPlugId(portName);
          return {
            ...node,
            data: {
              ...node.data,
              plugs: { ...node.data.plugs, [portName]: [...plugs, appended] },
              bindings: { ...node.data.bindings, [appended]: label },
            },
          };
        }),
      );
    },
    [],
  );

  /**
   * Resolve which input the pointer is over by hit testing the real React Flow
   * handles. Reading the topmost element would fail, because the edge component
   * renders a bend-handle layer above the node cards.
   */
  const plugUnder = React.useCallback(
    (clientX: number, clientY: number) => {
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
      const handle = best?.handle;
      if (!handle) return null;
      const raw = handle.getAttribute("data-handleid");
      const decoded = decodeHandleId(raw);
      if (!decoded || decoded.direction !== "input") return null;
      const node = nodes.find((candidate) => candidate.id === handle.dataset.nodeid);
      if (node?.type !== CARD_NODE_TYPE) return null;
      const port = node.data.spec.inputs.find(
        (candidate) => candidate.name === decoded.portName,
      );
      if (!port) return null;
      return { node, port, plugId: decoded.plugId, handleId: raw ?? "" };
    },
    [nodes],
  );

  const onDragOver = React.useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      const artifactId = draggingRef.current;
      if (!artifactId) return;
      event.preventDefault();
      const artifact = artifactById(artifactId);
      const plug = plugUnder(event.clientX, event.clientY);
      if (!artifact || !plug) {
        setHover({
          text: "Drop here to place a display of this artifact. Nothing runs from it.",
          ok: true,
        });
        return;
      }
      const ok = connectionArtifactContractIsValid({
        sourceHandle: handleIdFor(placedPort(artifact), undefined, "output"),
        targetHandle: plug.handleId,
      });
      setHover({
        text: ok
          ? `Release to satisfy ${plug.port.name}.`
          : `This input accepts ${portTypeLabel(plug.port)}, not ${artifact.artifactType}@${artifact.schemaVersion}.`,
        ok,
      });
    },
    [plugUnder],
  );

  const dropOnPlug = React.useCallback(
    (
      node: CardNode,
      port: Port,
      plugId: string | undefined,
      artifact: DrawerArtifact,
    ) => {
      const plugs = node.data.plugs[port.name] ?? [];
      const targetPlug = plugId ?? plugs[0] ?? newPlugId(port.name);
      const many = port.shape === "many" || port.accepted_shapes.includes("many");

      if (many) {
        const count = plugs.length + (plugs.some((id) => !node.data.bindings[id]) ? 0 : 1);
        addPlug(node.id, port.name, artifact.label);
        setStatus({
          tone: "good",
          text: `${artifact.label} added to ${port.name}. The input now holds ${count} artifacts as one sequence, in row order.`,
        });
        return;
      }

      const held = node.data.bindings[targetPlug];
      const incoming = edges.find(
        (edge) =>
          edge.target === node.id &&
          edge.data?.enabled !== false &&
          decodeHandleId(edge.targetHandle)?.portName === port.name,
      );

      if (!held && !incoming) {
        setBinding(node.id, targetPlug, artifact.label);
        setStatus({
          tone: "good",
          text: `${artifact.label} now satisfies ${port.name} as an origin. The row replaces Connect input. No node was added and nothing is copied.`,
        });
        return;
      }

      if (variant === "refuse") {
        setStatus({
          tone: "bad",
          text: `Refused. ${port.name} is already satisfied by ${held ? `the origin ${held}` : "a wire from an upstream node"}. Nothing changed.`,
        });
        return;
      }

      setBinding(node.id, targetPlug, artifact.label);
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
        setStatus({
          tone: "good",
          text: `${artifact.label} replaced the wire on ${port.name}. The wire stays in the graph disabled, so the swap is one undo.`,
        });
        return;
      }
      setStatus({
        tone: "good",
        text: `${artifact.label} replaced the origin ${held} on ${port.name}.`,
      });
    },
    [addPlug, edges, setBinding, variant],
  );

  const onDrop = React.useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      const artifactId = event.dataTransfer.getData("text/plain") || draggingRef.current;
      draggingRef.current = null;
      setHover(null);
      const artifact = artifactId ? artifactById(artifactId) : undefined;
      if (!artifact) return;

      const plug = plugUnder(event.clientX, event.clientY);
      if (!plug) {
        const instance = instanceRef.current;
        if (!instance) return;
        const point = instance.screenToFlowPosition({
          x: event.clientX,
          y: event.clientY,
        });
        const size = 132;
        const display: DisplayNode = {
          id: `display-${artifact.id}-${Date.now()}`,
          type: DISPLAY_NODE_TYPE,
          position: { x: point.x - size / 2, y: point.y - size / 2 },
          selected: true,
          width: size,
          height: size,
          data: { artifactId: artifact.id },
        };
        setNodes((current) => [
          ...current.map((node) => ({ ...node, selected: false })),
          display,
        ]);
        setStatus({
          tone: "good",
          text: `${artifact.label} placed on the canvas as a display. Drag a corner to resize it. It is not a node and holds no value.`,
        });
        return;
      }

      if (
        !connectionArtifactContractIsValid({
          sourceHandle: handleIdFor(placedPort(artifact), undefined, "output"),
          targetHandle: plug.handleId,
        })
      ) {
        setStatus({
          tone: "bad",
          text: `Refused. ${artifact.artifactType}@${artifact.schemaVersion} cannot satisfy ${plug.port.name}, which accepts ${portTypeLabel(plug.port)}.`,
        });
        return;
      }
      dropOnPlug(plug.node, plug.port, plug.plugId, artifact);
    },
    [dropOnPlug, plugUnder],
  );

  const keepArtifact = React.useCallback(
    (artifact: DrawerArtifact, name: string) => {
      setNaming(null);
      if (kept.some((entry) => entry.id === artifact.id)) {
        setStatus({
          tone: "info",
          text: `${artifact.label} is already Kept. Keeping the same artifact twice still yields one Kept artifact, because identity is the artifact reference.`,
        });
        return;
      }
      setKept((current) => [...current, { ...artifact, label: name }]);
      setStatus({
        tone: "good",
        text: `${name} is now Kept. The row stays in Produced because the run still produced it. The Kept copy is Workspace-owned, so deleting this graph never deletes it.`,
      });
    },
    [kept],
  );

  const rows = tab === "produced" ? produced : kept;

  return (
    <SandboxShell
      title="Artifact drawer to input"
      note={VARIANTS.find((entry) => entry.id === variant)?.note ?? ""}
      variants={VARIANTS.map(({ id, label }) => ({ id, label }))}
      activeVariant={variant}
      onVariant={(id) => setVariant(id as VariantId)}
    >
      <div {...stylex.props(s.workbench)}>
        <div
          {...stylex.props(s.canvasWrap)}
          onDragOver={onDragOver}
          onDragLeave={() => setHover(null)}
          onDrop={onDrop}
        >
          <div {...stylex.props(s.canvas)}>
            <ReactFlow<SpikeNode, SpikeEdge>
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              edgeTypes={productEdgeTypes as EdgeTypes}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onInit={(instance) => {
                instanceRef.current = instance;
              }}
              onPaneClick={() =>
                setNodes((current) => current.map((node) => ({ ...node, selected: false })))
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
                gap={54}
                color={tokens.colorGrid}
              />
              <Controls showInteractive={false} />
            </ReactFlow>
          </div>
          {hover ? (
            <div {...stylex.props(s.hint, hover.ok ? s.statusGood : s.statusBad)}>
              {hover.text}
            </div>
          ) : null}
          <div
            data-status={status.tone}
            {...stylex.props(
              s.status,
              status.tone === "bad" ? s.statusBad : null,
              status.tone === "good" ? s.statusGood : null,
            )}
          >
            {status.text}
          </div>
        </div>

        <div {...stylex.props(s.drawer)}>
          <div {...stylex.props(s.tabs)}>
            <button
              type="button"
              {...stylex.props(s.tab, tab === "produced" ? s.tabActive : null)}
              onClick={() => setTab("produced")}
            >
              Produced · {produced.length}
            </button>
            <button
              type="button"
              {...stylex.props(s.tab, tab === "kept" ? s.tabActive : null)}
              onClick={() => setTab("kept")}
            >
              Kept · {kept.length}
            </button>
          </div>
          <p {...stylex.props(s.drawerNote)}>
            {tab === "produced"
              ? "What the last runs of this graph produced. A stale row came from an earlier run than the one on screen."
              : "Workspace-owned artifacts. Graphs reference them, and deleting a graph never deletes them."}
          </p>
          <div {...stylex.props(s.rows)}>
            {rows.map((artifact) =>
              naming?.id === artifact.id ? (
                <form
                  key={`naming-${artifact.id}`}
                  {...stylex.props(s.keepForm)}
                  onSubmit={(event) => {
                    event.preventDefault();
                    keepArtifact(artifact, naming.value.trim() || artifact.label);
                  }}
                >
                  <input
                    autoFocus
                    value={naming.value}
                    onChange={(event) =>
                      setNaming({ id: artifact.id, value: event.target.value })
                    }
                    {...stylex.props(s.input)}
                  />
                  <button type="submit" {...stylex.props(s.smallButton)}>
                    Keep
                  </button>
                </form>
              ) : (
                <div
                  key={`${tab}-${artifact.id}`}
                  draggable
                  onDragStart={(event) => {
                    draggingRef.current = artifact.id;
                    event.dataTransfer.setData("text/plain", artifact.id);
                    event.dataTransfer.effectAllowed = "copy";
                  }}
                  onDragEnd={() => {
                    draggingRef.current = null;
                    setHover(null);
                  }}
                  {...stylex.props(s.row)}
                >
                  <span
                    {...stylex.props(s.swatch)}
                    style={{
                      background: artifactTypeColor(
                        artifact.artifactType,
                        tokens.colorAccent,
                      ),
                    }}
                  />
                  <span {...stylex.props(s.rowLabel)}>{artifact.label}</span>
                  <span {...stylex.props(s.rowType)}>
                    {artifact.artifactType}@{artifact.schemaVersion} · rev{" "}
                    {artifact.revision}
                  </span>
                  {artifact.stale ? (
                    <span {...stylex.props(s.stale)}>STALE</span>
                  ) : null}
                  {tab === "produced" ? (
                    <button
                      type="button"
                      {...stylex.props(s.smallButton)}
                      onClick={() =>
                        setNaming({ id: artifact.id, value: artifact.label })
                      }
                    >
                      Keep
                    </button>
                  ) : null}
                </div>
              ),
            )}
          </div>
          <div {...stylex.props(s.drawerFoot)}>
            An input fed by a wire shows the upstream node. An input fed by an origin shows
            the artifact. Both use the same port row, so the difference has to come from the
            label, a badge, or the wire style.
          </div>
        </div>
      </div>
    </SandboxShell>
  );
}
