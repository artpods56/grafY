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
import { ChevronDown, Image as ImageIcon } from "lucide-react";

import { useTheme } from "@/components/theme";
import { tokens } from "@/lib/stylex/tokens.stylex";
import type { InputPlugInput, NodeSpec, Port } from "@/lib/api";
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
import { artifactTypeColor } from "@/features/workbench/canvas/nodes.css";
import {
  DEFAULT_CANVAS_GRID_SETTINGS,
  shouldSnapPosition,
  shouldSnapSize,
  snapLength,
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
import { SandboxShell } from "../../SandboxShell";
import {
  DRAWER_ARTIFACTS,
  IMPORT_TABLE_SPEC,
  LIBRARY_ARTIFACTS,
  LIBRARY_FOLDERS,
  RENDER_PAGE_SPEC,
  RUN_BATCHES,
  SUMMARIZE_TABLES_SPEC,
  sandboxWorkspaceContext,
  type DrawerArtifact,
  type LibraryFolder,
  type RunBatch,
} from "../../fixtures/drawer";

const DISPLAY_NODE_TYPE = "sandboxArtifactDisplay";

/** A card dropped on empty canvas is a grid cell block, like every other card. */
const PLACED_MIN_SIZE = 56;

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

interface ArtifactDisplayData extends Record<string, unknown> {
  artifactId: string;
}

/**
 * A card is a real workflow node. The spike drives the product's own node body
 * so the drawer feeds the surface that ships, not a copy of it.
 */
type CardNode = Node<WorkflowNodeData, typeof WORKFLOW_NODE_TYPE>;
type DisplayNode = Node<ArtifactDisplayData, typeof DISPLAY_NODE_TYPE>;
type SpikeNode = CardNode | DisplayNode;
type SpikeEdge = Edge<WorkflowEdgeData, typeof WORKFLOW_EDGE_TYPE>;

function artifactById(id: string): DrawerArtifact | undefined {
  return DRAWER_ARTIFACTS.find((artifact) => artifact.id === id);
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

function ArtifactDisplayNode({ data, selected }: NodeProps<DisplayNode>) {
  const artifact = artifactById(data.artifactId);
  if (!artifact) return null;

  const color = artifactTypeColor(artifact.artifactType, tokens.colorAccent);

  return (
    <div {...stylex.props(s.displayFrame)}>
      <div {...stylex.props(s.displayLabelRow)}>
        <span {...stylex.props(s.displayType)}>
          <ImageIcon size={11} aria-hidden />
          {artifactFamilyTitle(artifact.artifactType)}
        </span>
        <span {...stylex.props(s.displayName)}>{artifact.label}</span>
      </div>
      <div {...stylex.props(s.display, selected ? s.displaySelected : null)}>
        <NodeResizer minWidth={56} minHeight={56} isVisible={selected} />
        <Handle
          type="source"
          position={Position.Right}
          id={encodeHandleId(portMetaForPort(placedPort(artifact)))}
          style={handleStyleAt("calc(50% - 7px)", color)}
        />
        <ArtifactBody artifact={artifact} />
      </div>
    </div>
  );
}

function placedPort(artifact: DrawerArtifact): Port {
  return {
    name: "placed",
    title: "placed",
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

function handleStyleAt(top: number | string, color: string) {
  const surface = tokens.colorSurface;
  return {
    top: typeof top === "number" ? `${top}px` : top,
    right: "-20px",
    width: "14px",
    height: "14px",
    borderRadius: "9999px",
    background: `radial-gradient(circle, ${surface} 0 3px, ${color} 3px 5px, transparent 5.5px)`,
    border: "none",
    cursor: "crosshair",
  };
}

/** The label the reference puts on the canvas above the card, not inside it. */
function artifactFamilyTitle(artifactType: string): string {
  const family = artifactFamily(artifactType);
  if (family === "image") return "Image";
  if (family === "table") return "Table";
  return "Text";
}

function artifactFamily(artifactType: string): "image" | "table" | "text" {
  if (
    artifactType.startsWith("file.png") ||
    artifactType.startsWith("image.")
  ) {
    return "image";
  }
  if (artifactType.startsWith("table.")) return "table";
  return "text";
}

function ArtifactBody({ artifact }: { artifact: DrawerArtifact }) {
  const family = artifactFamily(artifact.artifactType);
  if (family === "image") {
    return (
      <svg
        viewBox="0 0 100 100"
        preserveAspectRatio="xMidYMid slice"
        width="100%"
        height="100%"
      >
        <rect width="100" height="100" fill="#12212e" />
        <circle cx="68" cy="30" r="9" fill="#e6c07b" />
        <path
          d="M0 76 L30 52 L52 70 L74 46 L100 68 L100 100 L0 100 Z"
          fill="#3f6d59"
        />
        <path
          d="M0 88 L24 72 L48 86 L72 70 L100 84 L100 100 L0 100 Z"
          fill="#2c4c40"
        />
      </svg>
    );
  }
  if (family === "table") {
    return (
      <svg
        viewBox="0 0 100 100"
        preserveAspectRatio="xMidYMid slice"
        width="100%"
        height="100%"
      >
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
    <svg
      viewBox="0 0 100 100"
      preserveAspectRatio="xMidYMid slice"
      width="100%"
      height="100%"
    >
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
  ...productNodeTypes,
  [DISPLAY_NODE_TYPE]: ArtifactDisplayNode,
} as NodeTypes;

/**
 * The card's own plugs, wired to the spike's state so the product's add and
 * remove controls drive the same list the drawer drops into.
 */
function cardCallbacks(
  addPlug: (nodeId: string, portName: string) => void,
  removePlug: (nodeId: string, plugId: string) => void,
): Partial<WorkflowNodeData> {
  return {
    onAddInputPlug: addPlug,
    onRemoveInputPlug: removePlug,
  };
}

type DropOutcome =
  | { ok: false; reason: string }
  | { ok: true; data: WorkflowNodeData; sequenceLength: number };

/**
 * Satisfy one input with an artifact.
 *
 * A `one` port keeps a single origin, so a second artifact replaces the first on
 * the same row. A `many` port holds a sequence, so a drop onto a row that
already holds an artifact appends a new row instead of overwriting it.
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
const SANDBOX_PLUGS: Record<string, readonly InputPlugInput[]> = {
  import: [{ id: "sandbox-import-file-1", port: "file" }],
  summarize: [{ id: "sandbox-summarize-tables-1", port: "tables" }],
  render: [{ id: "sandbox-render-body-1", port: "body" }],
};

function cardNode(
  id: string,
  spec: NodeSpec,
  position: { x: number; y: number },
): CardNode {
  return {
    id,
    type: WORKFLOW_NODE_TYPE,
    position,
    selected: false,
    data: createWorkflowNodeData(spec, SANDBOX_PLUGS[id] ?? []),
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
  if (
    summarize?.type !== WORKFLOW_NODE_TYPE ||
    render?.type !== WORKFLOW_NODE_TYPE
  ) {
    return [];
  }
  const report = summarize.data.spec.outputs[0];
  const body = render.data.spec.inputs.find((port) => port.name === "body");
  const bodyPlug = inputPlugsForPort(render.data.inputPlugs, "body")[0];
  if (!report || !body || !bodyPlug) return [];

  return [
    {
      id: "edge-report-body",
      type: WORKFLOW_EDGE_TYPE,
      source: "summarize",
      target: "render",
      sourceHandle: portHandleId(report),
      targetHandle: plugHandleId(render.data, body, bodyPlug.id),
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
  displayFrame: {
    position: "relative",
    width: "100%",
    height: "100%",
  },
  displayLabelRow: {
    position: "absolute",
    bottom: "100%",
    left: 0,
    right: 0,
    marginBottom: "4px",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "8px",
    color: tokens.colorMuted,
    fontSize: "11px",
    lineHeight: 1.2,
    pointerEvents: "none",
  },
  displayType: {
    display: "inline-flex",
    alignItems: "center",
    gap: "4px",
    flexShrink: 0,
  },
  displayName: {
    overflow: "hidden",
    textOverflow: "ellipsis",
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

  workbench: {
    display: "grid",
    gridTemplateColumns: "240px minmax(0, 1fr) 280px",
    height: "calc(100svh - 208px)",
    minHeight: "460px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusMd,
    overflow: "hidden",
    backgroundColor: tokens.colorBg,
  },
  canvasColumn: {
    display: "flex",
    flexDirection: "column",
    minWidth: 0,
    minHeight: 0,
  },
  canvasWrap: {
    position: "relative",
    flex: 1,
    minWidth: 0,
    minHeight: 0,
  },
  canvas: { width: "100%", height: "100%" },
  status: {
    flexShrink: 0,
    minHeight: "32px",
    display: "flex",
    alignItems: "center",
    padding: "6px 12px",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorBorder,
    backgroundColor: tokens.colorChrome,
    color: tokens.colorText,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
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
    gridTemplateRows: "auto minmax(0, 1fr) auto",
    minHeight: 0,
    minWidth: 0,
    borderLeftWidth: 1,
    borderLeftStyle: "solid",
    borderLeftColor: tokens.colorBorder,
    backgroundColor: tokens.colorChrome,
  },
  drawerHead: {
    display: "grid",
    gridTemplateColumns: "auto auto minmax(0, 1fr)",
    alignItems: "center",
    gap: "6px",
    padding: "9px 10px 7px",
    color: tokens.colorMuted,
  },
  drawerTitle: {
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    fontWeight: 600,
  },
  folder: { display: "grid", gap: "1px" },
  group: { paddingLeft: "10px", display: "grid", gap: "1px" },
  folderRow: {
    display: "grid",
    gridTemplateColumns: "auto minmax(0, 1fr) auto",
    alignItems: "center",
    gap: "6px",
    padding: "4px 6px",
    borderRadius: tokens.radiusSm,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
  },
  batchTitle: {
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeXs,
    fontWeight: 600,
  },
  saved: {
    flexShrink: 0,
    padding: "0 5px",
    borderRadius: "9999px",
    backgroundColor: tokens.colorSurfaceSunken,
    color: tokens.colorAccent,
    fontSize: "9px",
    fontWeight: 600,
  },
  drawerNote: {
    gridColumn: "3",
    color: tokens.colorMuted,
    fontSize: "10.5px",
    lineHeight: 1.4,
    textAlign: "right",
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
    display: "grid",
    gridTemplateColumns: "3px minmax(0, 1fr) auto",
    alignItems: "center",
    columnGap: "7px",
    rowGap: "1px",
    padding: "5px 6px",
    borderRadius: tokens.radiusSm,
    cursor: "grab",
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
  },
  swatch: {
    width: "3px",
    height: "100%",
    gridRow: "1 / span 2",
    borderRadius: "9999px",
  },
  rowMeta: {
    gridColumn: "2 / span 2",
    display: "flex",
    alignItems: "center",
    gap: "6px",
    minWidth: 0,
  },
  rowLabel: {
    minWidth: 0,
    overflow: "hidden",
    color: tokens.colorText,
    fontSize: tokens.fontSizeXs,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  rowType: {
    flexShrink: 0,
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

interface RowHandlers {
  kept: readonly DrawerArtifact[];
  naming: { id: string; value: string } | null;
  setNaming: React.Dispatch<
    React.SetStateAction<{ id: string; value: string } | null>
  >;
  onDragStart: (
    artifact: DrawerArtifact,
  ) => (event: React.DragEvent<HTMLDivElement>) => void;
  onKeep: (artifact: DrawerArtifact, name: string) => void;
}

/**
 * One artifact row. The same row serves both drawers, because the gesture is
 * identical: drag it onto a port, or drag it onto empty canvas. The only
 * difference is whether the run that made it can save it into the library.
 */
function ArtifactRow({
  artifact,
  saved,
  canSave,
  naming,
  setNaming,
  onDragStart,
  onKeep,
}: RowHandlers & {
  artifact: DrawerArtifact;
  saved: boolean;
  canSave: boolean;
}) {
  if (naming?.id === artifact.id) {
    return (
      <form
        {...stylex.props(s.keepForm)}
        onSubmit={(event) => {
          event.preventDefault();
          onKeep(artifact, naming.value.trim() || artifact.label);
        }}
      >
        <input
          autoFocus
          aria-label="Name the library copy"
          value={naming.value}
          onChange={(event) =>
            setNaming({ id: artifact.id, value: event.target.value })
          }
          {...stylex.props(s.input)}
        />
        <button type="submit" {...stylex.props(s.smallButton)}>
          Save
        </button>
      </form>
    );
  }

  return (
    <div
      draggable
      data-artifact-row={artifact.label}
      data-saved={saved ? "true" : undefined}
      onDragStart={onDragStart(artifact)}
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
      {saved ? <span {...stylex.props(s.saved)}>saved</span> : null}
      {canSave ? (
        <button
          type="button"
          {...stylex.props(s.smallButton)}
          onClick={() => setNaming({ id: artifact.id, value: artifact.label })}
        >
          Save
        </button>
      ) : null}
      <span {...stylex.props(s.rowMeta)}>
        <span {...stylex.props(s.rowType)}>
          {artifact.artifactType}@{artifact.schemaVersion} · rev{" "}
          {artifact.revision}
        </span>
      </span>
    </div>
  );
}

function DrawerHead({
  title,
  note,
}: {
  title: string;
  note: string;
}) {
  return (
    <div {...stylex.props(s.drawerHead)}>
      <span {...stylex.props(s.drawerTitle)}>{title}</span>
      <ChevronDown size={13} aria-hidden />
      <span {...stylex.props(s.drawerNote)}>{note}</span>
    </div>
  );
}

function LibraryDrawer({
  folders,
  ...handlers
}: RowHandlers & { folders: readonly LibraryFolder[] }) {
  // Saved artifacts join the folder that matches their type, so the library is
  // the live list rather than a static tree.
  const saved = handlers.kept.filter(
    (entry) =>
      !folders.some((folder) =>
        folder.artifacts.some((artifact) => artifact.id === entry.id),
      ),
  );
  const isSaved = (artifact: DrawerArtifact) =>
    handlers.kept.some((entry) => entry.id === artifact.id);

  return (
    <aside {...stylex.props(s.drawer)} aria-label="Artifacts">
      <DrawerHead
        title="Artifacts"
        note="A folder tree, so one panel shows the same shape as files on disk. This is where the brief puts the library."
      />
      <div {...stylex.props(s.rows)}>
        {folders.map((folder) => (
          <div key={folder.name} {...stylex.props(s.folder)}>
            <div {...stylex.props(s.folderRow)}>
              <ChevronDown
                size={11}
                aria-hidden
                style={{
                  transform: folder.open ? undefined : "rotate(-90deg)",
                }}
              />
              <span {...stylex.props(s.rowLabel)}>{folder.name}</span>
            </div>
            {folder.open
              ? folder.artifacts.map((artifact) => (
                  <ArtifactRow
                    key={artifact.id}
                    artifact={artifact}
                    saved={isSaved(artifact)}
                    canSave={false}
                    {...handlers}
                  />
                ))
              : null}
          </div>
        ))}
        {saved.length ? (
          <div {...stylex.props(s.folder)}>
            <div {...stylex.props(s.folderRow)}>
              <ChevronDown size={11} aria-hidden />
              <span {...stylex.props(s.rowLabel)}>saved</span>
            </div>
            {saved.map((artifact) => (
              <ArtifactRow
                key={`saved-${artifact.id}`}
                artifact={artifact}
                saved
                canSave={false}
                {...handlers}
              />
            ))}
          </div>
        ) : null}
      </div>
      <div {...stylex.props(s.drawerFoot)}>
        Workspace-owned. A graph references these, so deleting a graph never
        deletes them. A saved copy is the same artifact in a second place, not a
        second artifact.
      </div>
    </aside>
  );
}

function RunDrawer({
  batches,
  ...handlers
}: RowHandlers & { batches: readonly RunBatch[] }) {
  const isSaved = (artifact: DrawerArtifact) =>
    handlers.kept.some((entry) => entry.id === artifact.id);

  return (
    <aside {...stylex.props(s.drawer)} aria-label="Generated">
      <DrawerHead
        title="Generated"
        note="What this graph produced, newest first, grouped by the node that made it. The brief puts the transient inbox here."
      />
      <div {...stylex.props(s.rows)}>
        {batches.map((batch) => (
          <div key={batch.heading} {...stylex.props(s.folder)}>
            <div {...stylex.props(s.folderRow)}>
              <span {...stylex.props(s.batchTitle)}>{batch.heading}</span>
              <span {...stylex.props(s.rowType)}>{batch.stamp}</span>
            </div>
            {batch.groups.map((group) => (
              <div key={group.node} {...stylex.props(s.group)}>
                <div {...stylex.props(s.folderRow)}>
                  <ChevronDown size={11} aria-hidden />
                  <span {...stylex.props(s.rowLabel)}>{group.node}</span>
                  <span {...stylex.props(s.rowType)}>{group.time}</span>
                </div>
                {group.artifacts.map((artifact) => (
                  <ArtifactRow
                    key={artifact.id}
                    artifact={artifact}
                    saved={isSaved(artifact)}
                    canSave
                    {...handlers}
                  />
                ))}
              </div>
            ))}
          </div>
        ))}
      </div>
      <div {...stylex.props(s.drawerFoot)}>
        A run from yesterday stays here. An input can still take it, and the row
        carries the revision it came from.
      </div>
    </aside>
  );
}

export function DrawerInteractionSpike() {
  const { resolved } = useTheme();
  const [variant, setVariant] = React.useState<VariantId>("replace");
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
  const [kept, setKept] =
    React.useState<readonly DrawerArtifact[]>(LIBRARY_ARTIFACTS);
  const [naming, setNaming] = React.useState<{
    id: string;
    value: string;
  } | null>(null);
  const [status, setStatus] = React.useState<{
    tone: "info" | "good" | "bad";
    text: string;
  }>({
    tone: "info",
      text: "Drag a row from the library on the left, or from Generated on the right, onto a port or onto empty canvas.",
  });
  const [hover, setHover] = React.useState<{
    text: string;
    ok: boolean;
  } | null>(null);
  const draggingRef = React.useRef<string | null>(null);
  const instanceRef = React.useRef<ReactFlowInstance<
    SpikeNode,
    SpikeEdge
  > | null>(null);

  const onNodesChange = React.useCallback(
    (changes: NodeChange<SpikeNode>[]) => {
      const cellSize = DEFAULT_CANVAS_GRID_SETTINGS.cellSize;
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
            position: snapPosition(change.position, cellSize),
          };
        }
        if (
          change.type === "dimensions" &&
          change.dimensions &&
          shouldSnapSize(DEFAULT_CANVAS_GRID_SETTINGS, {
            drafting: change.resizing === true,
            bypass: false,
          })
        ) {
          const { width, height } = change.dimensions;
          return {
            ...change,
            dimensions: {
              width: snapLength(width, cellSize, PLACED_MIN_SIZE),
              height: snapLength(height, cellSize, PLACED_MIN_SIZE),
            },
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
        node.id === nodeId && node.type === WORKFLOW_NODE_TYPE
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
        if (node.id !== nodeId || node.type !== WORKFLOW_NODE_TYPE) {
          return node;
        }
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
   * origin on its row. A live wire on that port is disabled by the caller, never
   * removed.
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
      if (node?.type !== WORKFLOW_NODE_TYPE) {
        return { ok: false, reason: "unknown node" };
      }
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
          candidate.id === nodeId && candidate.type === WORKFLOW_NODE_TYPE
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
      const node = nodesRef.current.find(
        (candidate) => candidate.id === handle.dataset.nodeid,
      );
      if (node?.type !== WORKFLOW_NODE_TYPE) return null;
      const port = node.data.spec.inputs.find(
        (candidate) => candidate.name === decoded.portName,
      );
      if (!port) return null;
      // React Flow writes `data-handleid` once, at mount, so it goes stale when
      // the plug on that row is replaced. The row element is the live identity.
      const rowPlugId = handle
        .closest<HTMLElement>("[data-input-plug-id]")
        ?.dataset.inputPlugId;
      return {
        node,
        port,
        plugId: rowPlugId ?? decoded.plugId,
        handleId: raw ?? "",
      };
    },
    [],
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
        sourceHandle: encodeHandleId(portMetaForPort(placedPort(artifact))),
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
      const live = nodesRef.current.find(
        (candidate) => candidate.id === node.id,
      );
      if (live?.type !== WORKFLOW_NODE_TYPE) return;
      node = live;
      const plugs = inputPlugsForPort(node.data.inputPlugs, port.name);
      const targetPlug = plugId ?? plugs[0]?.id;
      const many =
        port.shape === "many" || port.accepted_shapes.includes("many");

      if (many) {
        const bound = plugs.filter(
          (plug) => node.data.inputPlugBindings[plug.id],
        ).length;
        satisfyPlug(node.id, port.name, targetPlug, artifact.label);
        setStatus({
          tone: "good",
          text: `${artifact.label} added to ${port.name}. The input now holds ${bound + 1} artifacts as one sequence, in plug order.`,
        });
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

      if (!held && !incoming) {
        satisfyPlug(node.id, port.name, targetPlug, artifact.label);
        setStatus({
          tone: "good",
          text: `${artifact.label} now satisfies ${port.name} as an origin. The row shows the artifact, and the handle becomes a square. No node was added and nothing is copied.`,
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
    [edges, satisfyPlug, variant],
  );

  const onDrop = React.useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      const artifactId =
        event.dataTransfer.getData("text/plain") || draggingRef.current;
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
          position: snapPosition(
            { x: point.x - size / 2, y: point.y - size / 2 },
            DEFAULT_CANVAS_GRID_SETTINGS.cellSize,
          ),
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
          sourceHandle: encodeHandleId(portMetaForPort(placedPort(artifact))),
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
          text: `${artifact.label} is already in the library. Saving the same artifact twice still yields one library entry, because identity is the artifact reference.`,
        });
        return;
      }
      setKept((current) => [...current, { ...artifact, label: name }]);
      setStatus({
        tone: "good",
        text: `${name} is now in the library, as a copy that keeps its identity. The run row stays in the right drawer because the run still produced it.`,
      });
    },
    [kept],
  );

  const beginDrag = React.useCallback(
    (artifact: DrawerArtifact) => (event: React.DragEvent<HTMLDivElement>) => {
      draggingRef.current = artifact.id;
      event.dataTransfer.setData("text/plain", artifact.id);
      event.dataTransfer.effectAllowed = "copy";
    },
    [],
  );

  const canvasNodes = React.useMemo(
    () =>
      nodes.map((node) =>
        node.type === WORKFLOW_NODE_TYPE
          ? {
              ...node,
              data: {
                ...node.data,
                ...cardCallbacks(addPlugRow, removePlugRow),
              },
            }
          : node,
      ),
    [addPlugRow, nodes, removePlugRow],
  );

  return (
    <WorkspaceContextScope value={sandboxWorkspaceContext()}>
      <SandboxShell
        title="Artifact drawer to input"
        note={VARIANTS.find((entry) => entry.id === variant)?.note ?? ""}
        variants={VARIANTS.map(({ id, label }) => ({ id, label }))}
        activeVariant={variant}
        onVariant={(id) => setVariant(id as VariantId)}
      >
        <div {...stylex.props(s.workbench)}>
          <div {...stylex.props(s.canvasColumn)}>
            <div
              {...stylex.props(s.canvasWrap)}
              onDragOver={onDragOver}
              onDragLeave={() => setHover(null)}
              onDrop={onDrop}
            >
              <div {...stylex.props(s.canvas)}>
                <ReactFlow<SpikeNode, SpikeEdge>
                  nodes={canvasNodes}
                  edges={edges}
                  nodeTypes={nodeTypes}
                  edgeTypes={productEdgeTypes as EdgeTypes}
                  onNodesChange={onNodesChange}
                  onEdgesChange={onEdgesChange}
                  onInit={(instance) => {
                    instanceRef.current = instance;
                  }}
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
              {hover ? (
                <div
                  {...stylex.props(
                    s.hint,
                    hover.ok ? s.statusGood : s.statusBad,
                  )}
                >
                  {hover.text}
                </div>
              ) : null}
            </div>
            <div
              data-status={status.tone}
              {...stylex.props(
                s.status,
                status.tone === "bad" ? s.statusBad : null,
              )}
            >
              {status.text}
            </div>
          </div>

          <LibraryDrawer
            folders={LIBRARY_FOLDERS}
            kept={kept}
            naming={naming}
            setNaming={setNaming}
            onDragStart={beginDrag}
            onKeep={keepArtifact}
          />
          <RunDrawer
            batches={RUN_BATCHES}
            kept={kept}
            naming={naming}
            setNaming={setNaming}
            onDragStart={beginDrag}
            onKeep={keepArtifact}
          />
        </div>
      </SandboxShell>
    </WorkspaceContextScope>
  );
}
