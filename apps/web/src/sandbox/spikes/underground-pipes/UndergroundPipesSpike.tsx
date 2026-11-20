"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import {
  Controls,
  Panel,
  ReactFlow,
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type ConnectionLineComponent,
  type Edge,
  type EdgeChange,
  type EdgeTypes,
  type Node,
  type NodeChange,
  type NodeTypes,
  useNodesInitialized,
  useReactFlow,
  useStore,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { useTheme, type ResolvedTheme } from "@/components/theme";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Slider } from "@/components/ui/slider";
import { Surface } from "@/components/ui/surface";
import { tokens } from "@/lib/stylex/tokens.stylex";
import type { NodeSpec } from "@/lib/api";
import {
  edgeTypes as productEdgeTypes,
  nodeTypes as productNodeTypes,
} from "@/features/workbench/canvas/WorkflowCanvas";
import { encodeHandleId } from "@/features/workbench/canvas/handles";
import { inputPlugsForPort } from "@/features/workbench/canvas/input-plugs";
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
import {
  GlassStage,
  PipeConnectionLine,
  PipeEdgeView,
  PipeTargetsProvider,
  cornerRadius,
  pipeColor,
  type PipeCorners,
  type PipeLook,
  type PipeMaterial,
  type PipeWell,
} from "./pipe-layers";
import { PIPE_EDGE_TYPE, PipeRouter, RouteBook } from "./pipe-router";
import {
  DESIGN_PASSES,
  PIPE_FAMILIES,
  type DesignPass,
  type PipeFamily,
} from "./pipe-designs";
import {
  connectorCss,
  opusConnectorCss,
  portColorCss,
} from "./connector-designs";
import {
  DEFAULT_PIPE_ROUTER,
  PIPE_ROUTERS,
  pipeRouter,
  type PipeRouterId,
} from "./routing";

/**
 * Cards stand on a pane of frosted glass; edges are angular pipes on the floor
 * under it, blurred by the frost and seen sharp only through the wells at the
 * ports. The panel switches to the product's current edges on the same graph
 * and tunes the glass. No grid: it would sit on the glass and flatten it.
 */
type CardNode = Node<WorkflowNodeData, typeof WORKFLOW_NODE_TYPE>;
type SpikeEdge = Edge<WorkflowEdgeData>;
type EdgeStyle = "pipes" | "current";
type GraphKind = "demo" | "stress";
type SpikeGraph = { nodes: CardNode[]; edges: SpikeEdge[] };

const nodeTypes = { ...productNodeTypes } as NodeTypes;

/**
 * Built once: every port on every card reads this context (through the
 * artifact type catalog), so a new object per render re-rendered all of them
 * on each frame of a drag.
 */
const SANDBOX_WORKSPACE_CONTEXT = sandboxWorkspaceContext();
const edgeTypes = {
  ...productEdgeTypes,
  [PIPE_EDGE_TYPE]: PipeEdgeView,
} as EdgeTypes;

/** Stable plug ids, so the server and the client render the same rows. */
const SANDBOX_PLUGS = {
  import: [{ id: "pipes-seed-import-file", port: "file" }],
  summarize: [{ id: "pipes-seed-summarize-tables", port: "tables" }],
  render: [{ id: "pipes-seed-render-body", port: "body" }],
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

/** The handle a card publishes for one plug of an input. */
function plugHandle(
  node: CardNode,
  portName: string,
  plugId: string,
): string | null {
  const port = node.data.spec.inputs.find((input) => input.name === portName);
  if (!port) return null;
  return encodeHandleId(
    portMetaForPort(port, port.shape, plugId, node.data.artifactTypeBindings),
  );
}

/** The handle a card publishes for an input's first plug. */
function firstPlugHandle(node: CardNode, portName: string): string | null {
  const plug = inputPlugsForPort(node.data.inputPlugs, portName)[0];
  return plug ? plugHandle(node, portName, plug.id) : null;
}

/** The handle a card publishes for its first output. */
function firstOutputHandle(node: CardNode): string | null {
  const port = node.data.spec.outputs[0];
  return port ? encodeHandleId(portMetaForPort(port)) : null;
}

function wire(
  id: string,
  source: CardNode,
  target: CardNode,
  targetHandle: string | null,
): SpikeEdge[] {
  const sourceHandle = firstOutputHandle(source);
  if (!sourceHandle || !targetHandle) return [];
  return [
    {
      id,
      source: source.id,
      target: target.id,
      sourceHandle,
      targetHandle,
      data: { enabled: true, collectionMode: "direct" },
    },
  ];
}

const IMPORT_TABLE_LIST_SPEC: NodeSpec = {
  ...IMPORT_TABLE_SPEC,
  title: "Import tables",
  outputs: IMPORT_TABLE_SPEC.outputs.map((port) => ({
    ...port,
    title: "tables",
    shape: "many",
  })),
};

function initialState(): { nodes: CardNode[]; edges: SpikeEdge[] } {
  const importer = cardNode("import", IMPORT_TABLE_LIST_SPEC, { x: 0, y: 0 });
  const summarize = cardNode("summarize", SUMMARIZE_TABLES_SPEC, {
    x: 420,
    y: 200,
  });
  // Left of the report it reads, so its pipe has to double back.
  const render = cardNode("render", RENDER_PAGE_SPEC, { x: 40, y: 420 });
  return {
    nodes: [importer, summarize, render],
    edges: [
      ...wire(
        "pipe-table",
        importer,
        summarize,
        firstPlugHandle(summarize, "tables"),
      ),
      ...wire(
        "pipe-report",
        summarize,
        render,
        firstPlugHandle(render, "body"),
      ),
    ],
  };
}

/** One boot graph per page load, so the plug ids in the edges match the cards. */
let boot: SpikeGraph | null = null;

function bootState(): SpikeGraph {
  boot ??= initialState();
  return boot;
}

const STRESS_COLUMNS = 10;
const STRESS_ROWS = 6;
const STRESS_STEP = { x: 440, y: 380 };
/** Each stress card takes three pipes: from the left, from up-left, from up-right. */
const STRESS_SLOTS = ["left", "up-left", "up-right"] as const;

/**
 * A grid of cards, each fed by its left neighbour and both upper diagonals:
 * 60 cards and 144 pipes, a third of them running back under other cards.
 */
function stressState(): SpikeGraph {
  const grid: CardNode[][] = [];
  for (let row = 0; row < STRESS_ROWS; row += 1) {
    const line: CardNode[] = [];
    for (let column = 0; column < STRESS_COLUMNS; column += 1) {
      const importer = (row + column) % 3 === 0;
      const port = importer ? "file" : "tables";
      const id = `stress-${row}-${column}`;
      line.push({
        id,
        type: WORKFLOW_NODE_TYPE,
        position: { x: column * STRESS_STEP.x, y: row * STRESS_STEP.y },
        selected: false,
        data: createWorkflowNodeData(
          importer ? IMPORT_TABLE_LIST_SPEC : SUMMARIZE_TABLES_SPEC,
          STRESS_SLOTS.map((slot) => ({ id: `${id}-${slot}`, port })),
        ),
      });
    }
    grid.push(line);
  }

  const edges: SpikeEdge[] = [];
  for (const [row, line] of grid.entries()) {
    for (const [column, target] of line.entries()) {
      const port = target.data.spec.inputs[0]?.name ?? "";
      const feeds = [
        line[column - 1],
        grid[row - 1]?.[column - 1],
        grid[row - 1]?.[column + 1],
      ];
      for (const [index, source] of feeds.entries()) {
        const slot = STRESS_SLOTS[index];
        if (!source || !slot) continue;
        edges.push(
          ...wire(
            `stress-pipe-${target.id}-${slot}`,
            source,
            target,
            plugHandle(target, port, `${target.id}-${slot}`),
          ),
        );
      }
    }
  }
  return { nodes: grid.flat(), edges };
}

let stress: SpikeGraph | null = null;

function graphState(kind: GraphKind): SpikeGraph {
  if (kind === "demo") return bootState();
  stress ??= stressState();
  return stress;
}

/** Frames the page gets per second, averaged over half a second. */
function useFrameRate(): number | null {
  const [rate, setRate] = React.useState<number | null>(null);
  React.useEffect(() => {
    let frames = 0;
    let since = performance.now();
    let handle = 0;
    const tick = (now: number) => {
      frames += 1;
      if (now - since >= 500) {
        setRate(Math.round((frames * 1000) / (now - since)));
        frames = 0;
        since = now;
      }
      handle = requestAnimationFrame(tick);
    };
    handle = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(handle);
  }, []);
  return rate;
}

/**
 * Frames the whole graph after a swap. Right after the swap the store still
 * holds the old, measured cards, so wait for the new count as well.
 */
function FitOnGraphChange({
  graph,
  nodeCount,
}: {
  graph: GraphKind;
  nodeCount: number;
}) {
  const { fitView } = useReactFlow();
  const measured = useNodesInitialized();
  const storedCount = useStore((state) => state.nodeLookup.size);
  const fitted = React.useRef<GraphKind>("demo");
  const ready = measured && storedCount === nodeCount;
  React.useEffect(() => {
    if (!ready || fitted.current === graph) return;
    fitted.current = graph;
    void fitView({ padding: 0.12, maxZoom: 0.9 });
  }, [fitView, graph, ready]);
  return null;
}

function shadowInk(lightPercent: number, darkPercent: number): string {
  return `light-dark(color-mix(in srgb, black ${lightPercent}%, transparent), color-mix(in srgb, black ${darkPercent}%, transparent))`;
}

/** Cards stand on the glass: a contact shadow, then a soft one cast below. */
const CARD_REST_SHADOW = [
  `0 1px 2px ${shadowInk(10, 45)}`,
  `0 8px 20px -6px ${shadowInk(18, 55)}`,
  `0 22px 44px -14px ${shadowInk(16, 50)}`,
].join(", ");
/** Liquid glass cards: a bright top edge and a faint bottom one. */
const CARD_SPECULAR = [
  `inset 0 1px 0 light-dark(color-mix(in srgb, white 95%, transparent), color-mix(in srgb, white 24%, transparent))`,
  `inset 0 -1px 0 color-mix(in srgb, white 10%, transparent)`,
].join(", ");

/**
 * Spike-only styling of the product card, keyed on its data attributes. A
 * shipped version belongs in the card's own StyleX; this stays out of
 * workbench files, as the sandbox rules ask.
 *
 * Liquid cards are translucent without a backdrop-filter: what lies under a
 * card is already frosted glass, and a backdrop blur per card is recomputed for
 * every visible card on every frame of a pan.
 *
 * The product's pickup lift is switched off here: its spring moves the card's
 * handles for 200ms, and every one of those frames re-routes the card's pipes.
 * The shadow no longer changes with the lift either.
 */
const PIPES_SCOPE = '.grafy-pipes-spike[data-edges="pipes"]';
const CARD_CSS = `
.grafy-pipes-spike [data-node-tier] {
  transform: none;
  transition: none;
}
.grafy-pipes-spike [data-canvas-node-shell="true"] {
  transition: none;
}
.grafy-pipes-spike[data-edges="pipes"] [data-canvas-node-shell="true"] {
  box-shadow: ${CARD_REST_SHADOW};
}
.grafy-pipes-spike[data-edges="pipes"][data-material="liquid"] [data-canvas-node-shell="true"] {
  background-color: color-mix(in srgb, ${tokens.colorSurface} 58%, transparent);
  border-color: light-dark(color-mix(in srgb, white 85%, transparent), color-mix(in srgb, white 14%, transparent));
  box-shadow: ${CARD_SPECULAR}, ${CARD_REST_SHADOW};
}
${connectorCss(`${PIPES_SCOPE}[data-connector="sol"]`)}
${opusConnectorCss(`${PIPES_SCOPE}[data-connector="opus"]`)}
`;

const SPIKE_CSS = CARD_CSS;

/** Every artifact type a graph's ports carry, for their `--port` colours. */
function portTypeIds(graph: SpikeGraph): string[] {
  return graph.nodes.flatMap(({ data }) =>
    [...data.spec.inputs, ...data.spec.outputs].flatMap((port) =>
      port.artifact_type ? [port.artifact_type.id] : [],
    ),
  );
}

const s = stylex.create({
  canvas: {
    position: "relative",
    isolation: "isolate",
    width: "100%",
    height: "100svh",
    backgroundColor: tokens.colorBg,
    color: tokens.colorText,
  },
  // Scrolls once its rows outgrow the window, clear of the zoom controls.
  panel: {
    display: "grid",
    gap: "12px",
    width: "240px",
    maxHeight: "calc(100svh - 170px)",
    overflowY: "auto",
    overscrollBehavior: "contain",
  },
  row: { display: "grid", gap: "5px" },
  rowLabel: {
    color: tokens.colorMuted,
    fontSize: "10px",
    fontWeight: 800,
    letterSpacing: "0.08em",
    textTransform: "uppercase",
  },
  measure: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "baseline",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
  },
  rate: {
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    fontWeight: 700,
    fontVariantNumeric: "tabular-nums",
  },
  hint: {
    margin: 0,
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.4,
  },
});

function LookPanel({
  graph,
  onGraph,
  counts,
  edgeStyle,
  onEdgeStyle,
  look,
  onLook,
}: {
  graph: GraphKind;
  onGraph: (value: GraphKind) => void;
  counts: { cards: number; pipes: number };
  edgeStyle: EdgeStyle;
  onEdgeStyle: (value: EdgeStyle) => void;
  look: PipeLook;
  onLook: (value: PipeLook) => void;
}) {
  const pipes = edgeStyle === "pipes";
  const router = pipeRouter(look.router);
  const { resolved, setPreference } = useTheme();
  const frameRate = useFrameRate();
  return (
    <Surface tone="floating" padding="md" shape="lg" xstyle={s.panel}>
      <div {...stylex.props(s.row)}>
        <span {...stylex.props(s.rowLabel)}>Theme</span>
        <SegmentedControl<ResolvedTheme>
          aria-label="Theme"
          size="sm"
          value={resolved}
          onValueChange={setPreference}
          options={[
            { value: "light", label: "Light" },
            { value: "dark", label: "Dark" },
          ]}
        />
      </div>
      <div {...stylex.props(s.row)}>
        <span {...stylex.props(s.rowLabel)}>Graph</span>
        <SegmentedControl<GraphKind>
          aria-label="Graph"
          size="sm"
          value={graph}
          onValueChange={onGraph}
          options={[
            { value: "demo", label: "Demo" },
            { value: "stress", label: "Stress" },
          ]}
        />
        <div {...stylex.props(s.measure)}>
          <span>
            {counts.cards} cards · {counts.pipes} pipes
          </span>
          <span>
            <span {...stylex.props(s.rate)}>{frameRate ?? "–"}</span> fps
          </span>
        </div>
      </div>
      <div {...stylex.props(s.row)}>
        <span {...stylex.props(s.rowLabel)}>Edges</span>
        <SegmentedControl<EdgeStyle>
          aria-label="Edges"
          size="sm"
          value={edgeStyle}
          onValueChange={onEdgeStyle}
          options={[
            { value: "pipes", label: "Pipes" },
            { value: "current", label: "Current" },
          ]}
        />
      </div>
      <div {...stylex.props(s.row)}>
        <span {...stylex.props(s.rowLabel)}>Glass</span>
        <SegmentedControl<PipeMaterial>
          aria-label="Glass"
          size="sm"
          disabled={!pipes}
          value={look.material}
          onValueChange={(material) => onLook({ ...look, material })}
          options={[
            { value: "frost", label: "Frost" },
            { value: "liquid", label: "Liquid" },
          ]}
        />
      </div>
      <div {...stylex.props(s.row)}>
        <span {...stylex.props(s.rowLabel)}>Wells</span>
        <SegmentedControl<PipeWell>
          aria-label="Wells"
          size="sm"
          disabled={!pipes}
          value={look.well}
          onValueChange={(well) => onLook({ ...look, well })}
          options={[
            { value: "recessed", label: "Recessed" },
            { value: "flat", label: "Flat" },
          ]}
        />
      </div>
      <div {...stylex.props(s.row)}>
        <span {...stylex.props(s.rowLabel)}>Pipe</span>
        <SegmentedControl<PipeFamily>
          aria-label="Pipe"
          size="sm"
          disabled={!pipes}
          value={look.pipe}
          onValueChange={(pipe) => onLook({ ...look, pipe })}
          options={PIPE_FAMILIES}
        />
      </div>
      <div {...stylex.props(s.row)}>
        <span {...stylex.props(s.rowLabel)}>Pipe by</span>
        <SegmentedControl<DesignPass>
          aria-label="Pipe by"
          size="sm"
          disabled={!pipes}
          value={look.pipeBy}
          onValueChange={(pipeBy) => onLook({ ...look, pipeBy })}
          options={DESIGN_PASSES}
        />
      </div>
      <div {...stylex.props(s.row)}>
        <span {...stylex.props(s.rowLabel)}>Connector</span>
        <SegmentedControl<DesignPass>
          aria-label="Connector"
          size="sm"
          disabled={!pipes}
          value={look.connector}
          onValueChange={(connector) => onLook({ ...look, connector })}
          options={DESIGN_PASSES}
        />
      </div>
      <div {...stylex.props(s.row)}>
        <span {...stylex.props(s.rowLabel)}>Router</span>
        <SegmentedControl<PipeRouterId>
          aria-label="Router"
          size="sm"
          disabled={!pipes}
          value={look.router}
          onValueChange={(id) => onLook({ ...look, router: id })}
          options={PIPE_ROUTERS.map(({ id, label }) => ({ value: id, label }))}
        />
      </div>
      {(["dwell", "morph"] as const).map((key) => {
        const label = key === "dwell" ? "Dwell" : "Morph";
        return (
          <div {...stylex.props(s.row)} key={key}>
            <span {...stylex.props(s.rowLabel)}>{label}</span>
            <SegmentedControl<"on" | "off">
              aria-label={label}
              size="sm"
              disabled={!pipes}
              value={look[key] ? "on" : "off"}
              onValueChange={(value) =>
                onLook({ ...look, [key]: value === "on" })
              }
              options={[
                { value: "on", label: "On" },
                { value: "off", label: "Off" },
              ]}
            />
          </div>
        );
      })}
      <div {...stylex.props(s.row)}>
        <span {...stylex.props(s.rowLabel)}>Lanes</span>
        <SegmentedControl<"on" | "off">
          aria-label="Lanes"
          size="sm"
          disabled={!pipes || !router.supports.lanes}
          value={look.lanes ? "on" : "off"}
          onValueChange={(value) => onLook({ ...look, lanes: value === "on" })}
          options={[
            { value: "on", label: "On" },
            { value: "off", label: "Off" },
          ]}
        />
      </div>
      <div {...stylex.props(s.row)}>
        <span {...stylex.props(s.rowLabel)}>Depth layers</span>
        <SegmentedControl<"on" | "off">
          aria-label="Depth layers"
          size="sm"
          disabled={!pipes || !look.lanes || !router.supports.depth}
          value={look.depth ? "on" : "off"}
          onValueChange={(value) => onLook({ ...look, depth: value === "on" })}
          options={[
            { value: "on", label: "On" },
            { value: "off", label: "Off" },
          ]}
        />
      </div>
      <div {...stylex.props(s.row)}>
        <span {...stylex.props(s.rowLabel)}>Corners</span>
        <SegmentedControl<PipeCorners>
          aria-label="Corners"
          size="sm"
          disabled={!pipes}
          value={look.corners}
          onValueChange={(corners) => onLook({ ...look, corners })}
          options={[
            { value: "sharp", label: "Sharp" },
            { value: "rounded", label: "Rounded" },
          ]}
        />
      </div>
      <Slider
        label="Blur"
        min={0}
        max={12}
        step={0.1}
        format={(blur) => blur.toFixed(1)}
        disabled={!pipes}
        value={look.blur}
        onValueChange={(blur) => onLook({ ...look, blur })}
      />
      <Slider
        label="Frost"
        min={0}
        max={0.9}
        step={0.05}
        disabled={!pipes}
        value={look.frost}
        onValueChange={(frost) => onLook({ ...look, frost })}
      />
      <p {...stylex.props(s.hint)}>
        Hover or select a pipe to wipe the frost off it. Drag from an output to
        lay a new one.
      </p>
    </Surface>
  );
}

export function UndergroundPipesSpike() {
  const { resolved } = useTheme();
  const [graph, setGraph] = React.useState<GraphKind>("demo");
  const [nodes, setNodes] = React.useState<CardNode[]>(() => bootState().nodes);
  const [edges, setEdges] = React.useState<SpikeEdge[]>(
    () => bootState().edges,
  );

  const swapGraph = React.useCallback((kind: GraphKind) => {
    const next = graphState(kind);
    setGraph(kind);
    setNodes(next.nodes);
    setEdges(next.edges);
  }, []);
  const [edgeStyle, setEdgeStyle] = React.useState<EdgeStyle>("pipes");
  const [look, setLook] = React.useState<PipeLook>({
    router: DEFAULT_PIPE_ROUTER,
    dwell: true,
    morph: true,
    corners: "rounded",
    material: "liquid",
    well: "recessed",
    pipe: "glass",
    pipeBy: "opus",
    connector: "opus",
    lanes: true,
    depth: true,
    blur: 0.3,
    frost: 0.5,
  });
  const [pipeGroup, setPipeGroup] = React.useState<SVGGElement | null>(null);
  const [middlePipes, setMiddlePipes] = React.useState<SVGGElement | null>(
    null,
  );
  const [deepPipes, setDeepPipes] = React.useState<SVGGElement | null>(null);
  const [sharp, setSharp] = React.useState<SVGGElement | null>(null);
  const [wells, setWells] = React.useState<SVGGElement | null>(null);
  const [frostCuts, setFrostCuts] = React.useState<SVGGElement | null>(null);
  const [lenses, setLenses] = React.useState<SVGGElement | null>(null);
  const [lensMasks, setLensMasks] = React.useState<SVGGElement | null>(null);
  const [rims, setRims] = React.useState<SVGGElement | null>(null);
  const [book] = React.useState(() => new RouteBook());
  const [movingBook] = React.useState(() => new RouteBook());
  const [movingUnder, setMovingUnder] = React.useState<SVGGElement | null>(
    null,
  );
  const [movingOver, setMovingOver] = React.useState<SVGGElement | null>(null);
  const pipes = edgeStyle === "pipes";

  const onNodesChange = React.useCallback((changes: NodeChange<CardNode>[]) => {
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
  }, []);

  const onEdgesChange = React.useCallback(
    (changes: EdgeChange<SpikeEdge>[]) => {
      setEdges((current) => applyEdgeChanges(changes, current));
    },
    [],
  );

  const onConnect = React.useCallback((connection: Connection) => {
    setEdges((current) =>
      addEdge<SpikeEdge>(
        { ...connection, data: { enabled: true, collectionMode: "direct" } },
        current,
      ),
    );
  }, []);

  const typedEdges = React.useMemo(
    () =>
      edges.map((edge) =>
        pipes
          ? { ...edge, type: PIPE_EDGE_TYPE }
          : {
              ...edge,
              type: WORKFLOW_EDGE_TYPE,
              style: { stroke: pipeColor(edge.sourceHandle), strokeWidth: 2 },
            },
      ),
    [edges, pipes],
  );

  const targets = React.useMemo(
    () => ({
      book,
      movingBook,
      pipes: [pipeGroup, middlePipes, deepPipes],
      sharp,
      wells,
      frostCuts,
      lenses,
      lensMasks,
      rims,
      movingUnder,
      movingOver,
      look,
    }),
    [
      book,
      movingBook,
      pipeGroup,
      middlePipes,
      deepPipes,
      sharp,
      wells,
      frostCuts,
      lenses,
      lensMasks,
      rims,
      movingUnder,
      movingOver,
      look,
    ],
  );

  // The card CSS is scoped by a plain class, so merge it with StyleX's.
  const canvasStyle = stylex.props(s.canvas);
  const portCss = React.useMemo(
    () => portColorCss(PIPES_SCOPE, portTypeIds(graphState(graph))),
    [graph],
  );

  return (
    <WorkspaceContextScope value={SANDBOX_WORKSPACE_CONTEXT}>
      <PipeTargetsProvider value={targets}>
        <div
          className={`grafy-pipes-spike ${canvasStyle.className ?? ""}`}
          style={canvasStyle.style}
          data-edges={edgeStyle}
          data-material={look.material}
          data-connector={look.connector}
        >
          <style>{SPIKE_CSS + portCss}</style>
          <ReactFlow<CardNode, SpikeEdge>
            nodes={nodes}
            edges={typedEdges}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            connectionLineComponent={
              pipes
                ? (PipeConnectionLine as ConnectionLineComponent<CardNode>)
                : undefined
            }
            connectionLineStyle={{ stroke: tokens.colorAccent, strokeWidth: 2 }}
            fitView
            fitViewOptions={{ padding: 0.25, maxZoom: 0.9 }}
            minZoom={0.1}
            maxZoom={1.6}
            colorMode={resolved}
            connectOnClick={false}
            panOnScroll
            panOnDrag={[1, 2]}
            selectionOnDrag
            proOptions={{ hideAttribution: true }}
          >
            {pipes ? (
              <PipeRouter
                book={book}
                movingBook={movingBook}
                router={look.router}
                radius={cornerRadius(look.corners)}
                lanes={look.lanes}
                depth={look.depth}
                dwell={look.dwell}
                morph={look.morph}
              />
            ) : null}
            {pipes ? (
              <GlassStage
                look={look}
                onPipes={setPipeGroup}
                onMiddlePipes={setMiddlePipes}
                onDeepPipes={setDeepPipes}
                onSharp={setSharp}
                onWells={setWells}
                onFrostCuts={setFrostCuts}
                onLenses={setLenses}
                onLensMasks={setLensMasks}
                onRims={setRims}
                onMovingUnder={setMovingUnder}
                onMovingOver={setMovingOver}
              />
            ) : null}
            <FitOnGraphChange graph={graph} nodeCount={nodes.length} />
            <Panel position="top-left">
              <LookPanel
                graph={graph}
                onGraph={swapGraph}
                counts={{ cards: nodes.length, pipes: edges.length }}
                edgeStyle={edgeStyle}
                onEdgeStyle={setEdgeStyle}
                look={look}
                onLook={setLook}
              />
            </Panel>
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
      </PipeTargetsProvider>
    </WorkspaceContextScope>
  );
}
