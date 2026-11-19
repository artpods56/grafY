"use client";

import * as React from "react";
import { createPortal } from "react-dom";
import * as stylex from "@stylexjs/stylex";
import {
  Position,
  useStore,
  type ConnectionLineComponentProps,
  type Edge,
  type EdgeProps,
  type InternalNode,
  type ReactFlowState,
} from "@xyflow/react";

import { tokens } from "@/lib/stylex/tokens.stylex";
import { decodeHandleId } from "@/features/workbench/canvas/handles";
import { artifactTypeColor } from "@/features/workbench/canvas/nodes.css";
import {
  pipePath,
  routePipe,
  routePipes,
  type PipeRequest,
} from "./pipe-routing";

/**
 * Pipes on a floor under a pane of frosted glass; the cards stand on the glass.
 *
 *   1. floor     - the ground the pipes lie on, darker than the glass
 *   2. pipes     - every pipe body, blurred because it is seen through frost
 *   3. glass     - a frosted sheet with a well cut wherever a pipe comes up to
 *                  a port; through a well the pipe is seen sharp
 *   4. React Flow - cards, handles and an invisible hit path per edge
 *
 * A pipe edge computes its route where React Flow hands it the handle
 * positions, then portals its body under the glass, sharp stubs into the
 * wells, and its wells into the glass mask. Because a pipe lies under the
 * glass, it may run under a card: no route has to avoid nodes.
 *
 * Cost model, so the effect does not grow with the graph:
 *   - layers 2 and 3 are drawn once in flow units and moved with a CSS
 *     transform, like React Flow's own viewport; a pan re-renders and
 *     re-rasterises no SVG
 *   - one blur for the whole pipe layer, sized by the screen, not the graph
 *   - a well shows only the stub of its own pipe, sharp or refracted; a full
 *     sharp copy exists only for the pipe being hovered or selected
 *   - while a card is dragged, its pipes leave the blurred layer and the glass
 *     masks for a small overlay of their own, so a drag frame redraws those
 *     pipes and not the whole sheet
 *
 * Routes come from {@link PipeRouter}, which lays all resting pipes out
 * together so that pipes sharing a channel take lanes side by side. A pipe of
 * a dragged card routes on its own until the card is put down.
 */

export const PIPE_EDGE_TYPE = "pipe";
export type PipeEdge = Edge<Record<string, unknown>, typeof PIPE_EDGE_TYPE>;

export type PipeCorners = "sharp" | "rounded";
/**
 * `frost` is plain frosted glass. `liquid` borrows Apple's glass: colour seen
 * through it is boosted rather than washed out, the glass refracts (magnifies)
 * what lies under a well's lip, and its cut edges catch a specular highlight.
 */
export type PipeMaterial = "frost" | "liquid";

export interface PipeLook {
  corners: PipeCorners;
  material: PipeMaterial;
  /** Spread pipes that share a channel into lanes side by side. */
  lanes: boolean;
  /** Sink pipes a channel cannot hold into deeper, blurrier layers. */
  depth: boolean;
  /** Blur of a pipe seen through the glass, in flow units. */
  blur: number;
  /** How milky the glass is, 0 (clear) to 1 (opaque). */
  frost: number;
}

interface Point {
  x: number;
  y: number;
}

/** Flow-unit geometry. The ring is the product's 10px port mark. */
const PIPE_WIDTH = 8;
const PIPE_SHINE_WIDTH = 2.5;
const RING_RADIUS = 5;
const WELL_RADIUS = 12;
/** How far a pipe runs straight out of its well before its first turn. */
const ROUNDED_CORNER_RADIUS = 12;
/** Liquid glass: the lip around a well that refracts, and how much it magnifies. */
const LENS_RADIUS = 21;
const LENS_ZOOM = 1.4;
/** Half the side of the glass sheet, in flow units: past any reachable pan. */
const SHEET_REACH = 100_000;

/** One stage per page, so fixed ids are unique. */
const WELL_SHAPES_ID = "pipe-stage-well-shapes";
const FROST_MASK_ID = "pipe-stage-frost";
const CLEAR_MASK_ID = "pipe-stage-clear";
const WELL_SHADE_ID = "pipe-stage-well-shade";
const WELL_EDGE_ID = "pipe-stage-well-edge";
const WELL_SPECULAR_ID = "pipe-stage-well-specular";
const LENS_RING_ID = "pipe-stage-lens-ring";

/** The floor is darker than the glass, so a well reads as a hole. */
const FLOOR = `light-dark(color-mix(in srgb, ${tokens.colorBg} 88%, black), color-mix(in srgb, ${tokens.colorBg} 35%, black))`;
/** The glass edge at the bottom of a well catches the light. */
const WELL_GLINT =
  "light-dark(white, color-mix(in srgb, white 45%, transparent))";

/** How much more a layer blurs, and how much it fades, per step deeper. */
const DEPTH_BLUR_STEP = 0.9;
const DEPTH_OPACITY = [1, 0.72, 0.5] as const;

interface RoutedPath {
  path: string;
  depth: number;
}

/**
 * The resting pipes' paths and layers, published by {@link PipeRouter}. A pipe
 * subscribes to its own entry only, so a re-route re-renders just the pipes
 * that moved.
 */
export class RouteBook {
  private paths = new Map<string, RoutedPath>();
  private listeners = new Map<string, Set<() => void>>();

  get(id: string): RoutedPath | undefined {
    return this.paths.get(id);
  }

  subscribe(id: string, listener: () => void): () => void {
    const listeners = this.listeners.get(id) ?? new Set();
    listeners.add(listener);
    this.listeners.set(id, listeners);
    return () => {
      listeners.delete(listener);
    };
  }

  publish(next: ReadonlyMap<string, RoutedPath>): void {
    const changed: string[] = [];
    const paths = new Map<string, RoutedPath>();
    for (const [id, routed] of next) {
      const current = this.paths.get(id);
      // Keep the old object when nothing changed: it is the snapshot a pipe
      // compares against.
      if (current?.path === routed.path && current.depth === routed.depth) {
        paths.set(id, current);
      } else {
        paths.set(id, routed);
        changed.push(id);
      }
    }
    for (const id of this.paths.keys()) {
      if (!next.has(id)) changed.push(id);
    }
    this.paths = paths;
    for (const id of changed) {
      for (const listener of this.listeners.get(id) ?? []) listener();
    }
  }
}

interface PipeTargets {
  book: RouteBook;
  /** One blurred group per layer, the surface first. */
  pipes: readonly (SVGGElement | null)[];
  sharp: SVGGElement | null;
  wells: SVGGElement | null;
  lenses: SVGGElement | null;
  lensMasks: SVGGElement | null;
  rims: SVGGElement | null;
  movingUnder: SVGGElement | null;
  movingOver: SVGGElement | null;
  look: PipeLook;
}

const PipeTargetsContext = React.createContext<PipeTargets | null>(null);

export const PipeTargetsProvider = PipeTargetsContext.Provider;

const s = stylex.create({
  floor: {
    position: "absolute",
    inset: 0,
    zIndex: 1,
    pointerEvents: "none",
  },
  // A 1px plane at the flow origin, moved like React Flow's viewport. Not 0:
  // an SVG with no width draws nothing, and the global reset caps an SVG at
  // its parent's width.
  plane: {
    position: "absolute",
    top: 0,
    left: 0,
    width: "1px",
    height: "1px",
    overflow: "visible",
    pointerEvents: "none",
    transformOrigin: "0 0",
    willChange: "transform",
  },
  // React Flow's renderer (cards, handles, hit paths) sits at z-index 4.
  pipes: { zIndex: 1 },
  glass: { zIndex: 2 },
  planeSvg: {
    position: "absolute",
    top: 0,
    left: 0,
    width: "1px",
    height: "1px",
    overflow: "visible",
  },
});

type GroupRef = (group: SVGGElement | null) => void;

/** Layers 1 to 3. Edges fill them through {@link PipeTargetsProvider}. */
export function GlassStage({
  look,
  onPipes,
  onMiddlePipes,
  onDeepPipes,
  onSharp,
  onWells,
  onLenses,
  onLensMasks,
  onRims,
  onMovingUnder,
  onMovingOver,
}: {
  look: PipeLook;
  onPipes: GroupRef;
  onMiddlePipes: GroupRef;
  onDeepPipes: GroupRef;
  onSharp: GroupRef;
  onWells: GroupRef;
  onLenses: GroupRef;
  onLensMasks: GroupRef;
  onRims: GroupRef;
  onMovingUnder: GroupRef;
  onMovingOver: GroupRef;
}) {
  const x = useStore((state) => state.transform[0]);
  const y = useStore((state) => state.transform[1]);
  const zoom = useStore((state) => state.transform[2]);
  const viewport = `translate(${x}px, ${y}px) scale(${zoom})`;
  // A CSS filter runs in the element's own units, so this blur is in flow
  // units and scales with zoom by itself.
  const filterAt = (depth: number): string | undefined => {
    const filters: string[] = [];
    const blur = look.blur * (1 + depth * DEPTH_BLUR_STEP);
    if (blur > 0) filters.push(`blur(${blur}px)`);
    // Vibrancy: colour under Apple's glass is boosted rather than washed out.
    if (look.material === "liquid") filters.push("saturate(1.9)");
    return filters.length > 0 ? filters.join(" ") : undefined;
  };
  const filter = filterAt(0);
  const sheet = {
    x: -SHEET_REACH,
    y: -SHEET_REACH,
    width: SHEET_REACH * 2,
    height: SHEET_REACH * 2,
  };
  return (
    <>
      <div
        aria-hidden="true"
        {...stylex.props(s.floor)}
        style={{ backgroundColor: FLOOR }}
      />
      {/* Deepest first, so each layer lies under the one above it. */}
      <div
        aria-hidden="true"
        {...stylex.props(s.plane, s.pipes)}
        style={{
          transform: viewport,
          filter: filterAt(2),
          opacity: DEPTH_OPACITY[2],
        }}
      >
        <svg {...stylex.props(s.planeSvg)}>
          <g ref={onDeepPipes} />
        </svg>
      </div>
      <div
        aria-hidden="true"
        {...stylex.props(s.plane, s.pipes)}
        style={{
          transform: viewport,
          filter: filterAt(1),
          opacity: DEPTH_OPACITY[1],
        }}
      >
        <svg {...stylex.props(s.planeSvg)}>
          <g ref={onMiddlePipes} />
        </svg>
      </div>
      <div
        aria-hidden="true"
        {...stylex.props(s.plane, s.pipes)}
        style={{ transform: viewport, filter }}
      >
        <svg {...stylex.props(s.planeSvg)}>
          <g ref={onPipes} />
        </svg>
      </div>
      <div
        aria-hidden="true"
        {...stylex.props(s.plane, s.glass)}
        style={{ transform: viewport }}
      >
        <svg {...stylex.props(s.planeSvg)}>
          <defs>
            {/* Wells and wiped strips, drawn in currentColor so one set of
                shapes cuts the frost (black) and lets the sharp pipes through
                (white). */}
            <g id={WELL_SHAPES_ID} ref={onWells} />
            <mask id={FROST_MASK_ID} maskUnits="userSpaceOnUse" {...sheet}>
              <rect {...sheet} fill="white" />
              <use href={`#${WELL_SHAPES_ID}`} style={{ color: "black" }} />
            </mask>
            <mask id={CLEAR_MASK_ID} maskUnits="userSpaceOnUse" {...sheet}>
              <rect {...sheet} fill="black" />
              <use href={`#${WELL_SHAPES_ID}`} style={{ color: "white" }} />
            </mask>
            {/* Light from above: the glass shades the top of a well and its
                bottom edge glints. Symmetric shading reads as a ball, not a hole. */}
            <radialGradient id={WELL_SHADE_ID} cx="50%" cy="74%" r="74%">
              <stop offset="58%" stopColor="black" stopOpacity={0} />
              <stop offset="100%" stopColor="black" stopOpacity={0.38} />
            </radialGradient>
            <linearGradient id={WELL_EDGE_ID} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="black" stopOpacity={0.4} />
              <stop offset="50%" stopColor="black" stopOpacity={0} />
              <stop
                offset="100%"
                stopOpacity={0.95}
                style={{ stopColor: WELL_GLINT }}
              />
            </linearGradient>
            {/* Liquid glass: light from the top left glints on both sides of a
                cut edge. */}
            <linearGradient id={WELL_SPECULAR_ID} x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="white" stopOpacity={0.95} />
              <stop offset="32%" stopColor="white" stopOpacity={0} />
              <stop offset="68%" stopColor="white" stopOpacity={0} />
              <stop offset="100%" stopColor="white" stopOpacity={0.55} />
            </linearGradient>
            {/* The refracting lip: clear right at the well's edge, fading into
                the frost further out. */}
            <radialGradient id={LENS_RING_ID}>
              <stop
                offset={WELL_RADIUS / LENS_RADIUS - 0.02}
                stopColor="white"
                stopOpacity={0}
              />
              <stop
                offset={WELL_RADIUS / LENS_RADIUS}
                stopColor="white"
                stopOpacity={0.95}
              />
              <stop offset="0.8" stopColor="white" stopOpacity={0.45} />
              <stop offset="1" stopColor="white" stopOpacity={0} />
            </radialGradient>
            <g ref={onLensMasks} />
          </defs>
          {/* Pipes of a dragged card, blurred on their own and frosted with
              the rest. */}
          <g ref={onMovingUnder} style={{ filter }} />
          <rect
            {...sheet}
            mask={`url(#${FROST_MASK_ID})`}
            fillOpacity={look.frost}
            style={{ fill: tokens.colorBg }}
          />
          <g mask={`url(#${CLEAR_MASK_ID})`}>
            <g ref={onSharp} />
          </g>
          <g ref={onMovingOver} />
          <g ref={onLenses} />
          <g ref={onRims} />
        </svg>
      </div>
    </>
  );
}

/** React Flow anchors an edge on the ring's outer side; a pipe rises at its centre. */
function ringCentre(x: number, y: number, position: Position): Point {
  switch (position) {
    case Position.Left:
      return { x: x + RING_RADIUS, y };
    case Position.Right:
      return { x: x - RING_RADIUS, y };
    case Position.Top:
      return { x, y: y + RING_RADIUS };
    case Position.Bottom:
      return { x, y: y - RING_RADIUS };
  }
}

/** The first straight run of a pipe out of its well, toward its port's side. */
function stubPath(centre: Point, position: Position, length: number): string {
  switch (position) {
    case Position.Left:
      return `M${centre.x},${centre.y} H${centre.x - length}`;
    case Position.Right:
      return `M${centre.x},${centre.y} H${centre.x + length}`;
    case Position.Top:
      return `M${centre.x},${centre.y} V${centre.y - length}`;
    case Position.Bottom:
      return `M${centre.x},${centre.y} V${centre.y + length}`;
  }
}

/** The source port's type colour, as the product paints a saved edge. */
export function pipeColor(sourceHandleId: string | null | undefined): string {
  const handle = decodeHandleId(sourceHandleId);
  if (!handle?.artifactTypeId) return tokens.colorMuted;
  return artifactTypeColor(handle.artifactTypeId, tokens.colorMuted);
}

function cornerRadius(corners: PipeCorners): number {
  return corners === "sharp" ? 0 : ROUNDED_CORNER_RADIUS;
}

/** A pipe's route on its own, without lanes: for a pipe in motion. */
function soloPath(request: PipeRequest, corners: PipeCorners): string {
  return pipePath(routePipe(request), cornerRadius(corners));
}

/** The centre of a handle's ring, and the side of the card it sits on. */
function handleCentre(
  node: InternalNode,
  type: "source" | "target",
  handleId: string | null | undefined,
): { point: Point; side: Position } | null {
  const handles = node.internals.handleBounds?.[type] ?? [];
  const handle = handleId
    ? handles.find((candidate) => candidate.id === handleId)
    : handles[0];
  if (!handle) return null;
  const origin = node.internals.positionAbsolute;
  return {
    point: {
      x: origin.x + handle.x + handle.width / 2,
      y: origin.y + handle.y + handle.height / 2,
    },
    side: handle.position,
  };
}

/**
 * Every resting pipe's ports, as a string so the router re-runs only when one
 * of them moves. Pipes of a dragged card are left out until it is put down.
 */
function selectRestingPipes(state: ReactFlowState): string {
  const requests: PipeRequest[] = [];
  for (const edge of state.edges) {
    if (edge.type !== PIPE_EDGE_TYPE) continue;
    const sourceNode = state.nodeLookup.get(edge.source);
    const targetNode = state.nodeLookup.get(edge.target);
    if (!sourceNode || !targetNode) continue;
    if (sourceNode.dragging || targetNode.dragging) continue;
    const source = handleCentre(sourceNode, "source", edge.sourceHandle);
    const target = handleCentre(targetNode, "target", edge.targetHandle);
    if (!source || !target) continue;
    requests.push({
      id: edge.id,
      source: source.point,
      sourceSide: source.side,
      target: target.point,
      targetSide: target.side,
    });
  }
  return JSON.stringify(requests);
}

/** Lays out all resting pipes together and publishes their paths. */
export function PipeRouter({
  book,
  corners,
  lanes,
  depth,
}: {
  book: RouteBook;
  corners: PipeCorners;
  lanes: boolean;
  depth: boolean;
}) {
  const resting = useStore(selectRestingPipes);
  React.useLayoutEffect(() => {
    const requests = JSON.parse(resting) as PipeRequest[];
    const radius = cornerRadius(corners);
    const paths = new Map<string, RoutedPath>();
    for (const [id, routed] of routePipes(requests, { lanes, depth })) {
      paths.set(id, {
        path: pipePath(routed.points, radius),
        depth: routed.depth,
      });
    }
    book.publish(paths);
  }, [book, corners, depth, lanes, resting]);
  return null;
}

const NO_BOOK_SUBSCRIPTION = () => () => {};

/** A tube: the type colour with a lighter shine down its middle. */
function PipeBody({
  path,
  color,
  corners,
  girth = 1,
}: {
  path: string;
  color: string;
  corners: PipeCorners;
  /** Width multiplier; a refracted stub is drawn magnified. */
  girth?: number;
}) {
  const join = corners === "sharp" ? "miter" : "round";
  return (
    <g>
      <path
        d={path}
        fill="none"
        strokeWidth={PIPE_WIDTH * girth}
        strokeLinejoin={join}
        style={{ stroke: color }}
      />
      <path
        d={path}
        fill="none"
        strokeWidth={PIPE_SHINE_WIDTH * girth}
        strokeLinejoin={join}
        style={{ stroke: `color-mix(in srgb, ${color} 45%, white)` }}
      />
    </g>
  );
}

/** The well's cut edge in the glass: shade under its top, a glint along its bottom. */
function WellRim({
  centre,
  material,
}: {
  centre: Point;
  material: PipeMaterial;
}) {
  return (
    <g>
      <circle
        cx={centre.x}
        cy={centre.y}
        r={WELL_RADIUS}
        fill={`url(#${WELL_SHADE_ID})`}
      />
      <circle
        cx={centre.x}
        cy={centre.y}
        r={WELL_RADIUS}
        fill="none"
        strokeWidth={material === "liquid" ? 1.5 : 1.25}
        stroke={`url(#${
          material === "liquid" ? WELL_SPECULAR_ID : WELL_EDGE_ID
        })`}
      />
    </g>
  );
}

/**
 * A well drawn on top of the frost instead of cut out of it: the floor showing
 * through, and the stub rising in it. Used while a pipe moves, so the frost
 * mask stays put.
 */
function OpenWell({
  centre,
  position,
  color,
  corners,
}: {
  centre: Point;
  position: Position;
  color: string;
  corners: PipeCorners;
}) {
  return (
    <g>
      <circle
        cx={centre.x}
        cy={centre.y}
        r={WELL_RADIUS}
        style={{ fill: FLOOR }}
      />
      <PipeBody
        path={stubPath(centre, position, WELL_RADIUS)}
        color={color}
        corners={corners}
      />
    </g>
  );
}

function lensMaskId(edgeId: string, end: "source" | "target"): string {
  return `pipe-lens-${edgeId.replace(/[^\w-]/g, "_")}-${end}`;
}

/** Where a well's lip refracts: a ring around the well, in flow units. */
function LensMask({ id, centre }: { id: string; centre: Point }) {
  return (
    <mask
      id={id}
      maskUnits="userSpaceOnUse"
      x={centre.x - LENS_RADIUS}
      y={centre.y - LENS_RADIUS}
      width={LENS_RADIUS * 2}
      height={LENS_RADIUS * 2}
    >
      <circle
        cx={centre.x}
        cy={centre.y}
        r={LENS_RADIUS}
        fill={`url(#${LENS_RING_ID})`}
      />
    </mask>
  );
}

/**
 * Under a well's lip lies only the stub of its own pipe (the first turn is
 * further out than the lip), so the refraction draws that stub magnified.
 */
function Lens({
  id,
  centre,
  position,
  color,
  corners,
}: {
  id: string;
  centre: Point;
  position: Position;
  color: string;
  corners: PipeCorners;
}) {
  return (
    <g mask={`url(#${id})`}>
      <PipeBody
        path={stubPath(centre, position, LENS_RADIUS)}
        color={color}
        corners={corners}
        girth={LENS_ZOOM}
      />
    </g>
  );
}

export function PipeEdgeView({
  id,
  source: sourceId,
  target: targetId,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  sourceHandleId,
  selected,
}: EdgeProps<PipeEdge>) {
  const targets = React.useContext(PipeTargetsContext);
  const [hovered, setHovered] = React.useState(false);
  const moving = useStore(
    (state) =>
      Boolean(state.nodeLookup.get(sourceId)?.dragging) ||
      Boolean(state.nodeLookup.get(targetId)?.dragging),
  );
  const book = targets?.book;
  const subscribe = React.useCallback(
    (listener: () => void) => book?.subscribe(id, listener) ?? (() => {}),
    [book, id],
  );
  const routed = React.useSyncExternalStore(
    book ? subscribe : NO_BOOK_SUBSCRIPTION,
    () => book?.get(id),
    () => undefined,
  );
  if (!targets) return null;

  const { corners, material } = targets.look;
  const liquid = material === "liquid";
  const sourceLens = lensMaskId(id, "source");
  const targetLens = lensMaskId(id, "target");
  const source = ringCentre(sourceX, sourceY, sourcePosition);
  const target = ringCentre(targetX, targetY, targetPosition);
  const resting = moving ? undefined : routed;
  const layer = targets.pipes[resting?.depth ?? 0] ?? targets.pipes[0];
  const path =
    resting?.path ??
    soloPath(
      {
        id,
        source,
        sourceSide: sourcePosition,
        target,
        targetSide: targetPosition,
      },
      corners,
    );
  const color = pipeColor(sourceHandleId);
  // Selection wipes the frost off along the pipe; hover thins it halfway.
  // Not while moving: a wipe is cut into the frost mask.
  const wipe = moving ? 0 : selected ? 1 : hovered ? 0.5 : 0;
  // Settled pipes go into the shared layers, moving ones into the overlay.
  const settled = !moving;

  return (
    <>
      <path
        d={path}
        fill="none"
        stroke="transparent"
        strokeWidth={22}
        className="react-flow__edge-interaction"
        style={{ pointerEvents: "stroke" }}
        onPointerEnter={() => setHovered(true)}
        onPointerLeave={() => setHovered(false)}
      />
      {moving && targets.movingUnder
        ? createPortal(
            <PipeBody path={path} color={color} corners={corners} />,
            targets.movingUnder,
          )
        : null}
      {moving && targets.movingOver
        ? createPortal(
            <>
              <OpenWell
                centre={source}
                position={sourcePosition}
                color={color}
                corners={corners}
              />
              <OpenWell
                centre={target}
                position={targetPosition}
                color={color}
                corners={corners}
              />
            </>,
            targets.movingOver,
          )
        : null}
      {settled && layer
        ? createPortal(
            <g data-pipe={id}>
              <PipeBody path={path} color={color} corners={corners} />
            </g>,
            layer,
          )
        : null}
      {settled && targets.sharp
        ? createPortal(
            wipe > 0 ? (
              <PipeBody path={path} color={color} corners={corners} />
            ) : (
              <>
                <PipeBody
                  path={stubPath(source, sourcePosition, WELL_RADIUS)}
                  color={color}
                  corners={corners}
                />
                <PipeBody
                  path={stubPath(target, targetPosition, WELL_RADIUS)}
                  color={color}
                  corners={corners}
                />
              </>
            ),
            targets.sharp,
          )
        : null}
      {settled && targets.wells
        ? createPortal(
            <>
              <circle
                cx={source.x}
                cy={source.y}
                r={WELL_RADIUS}
                fill="currentColor"
              />
              <circle
                cx={target.x}
                cy={target.y}
                r={WELL_RADIUS}
                fill="currentColor"
              />
              {wipe > 0 ? (
                <path
                  d={path}
                  fill="none"
                  stroke="currentColor"
                  strokeOpacity={wipe}
                  strokeWidth={PIPE_WIDTH + 12}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                />
              ) : null}
            </>,
            targets.wells,
          )
        : null}
      {liquid && targets.lensMasks
        ? createPortal(
            <>
              <LensMask id={sourceLens} centre={source} />
              <LensMask id={targetLens} centre={target} />
            </>,
            targets.lensMasks,
          )
        : null}
      {liquid && targets.lenses
        ? createPortal(
            <>
              <Lens
                id={sourceLens}
                centre={source}
                position={sourcePosition}
                color={color}
                corners={corners}
              />
              <Lens
                id={targetLens}
                centre={target}
                position={targetPosition}
                color={color}
                corners={corners}
              />
            </>,
            targets.lenses,
          )
        : null}
      {targets.rims
        ? createPortal(
            <>
              <WellRim centre={source} material={material} />
              <WellRim centre={target} material={material} />
            </>,
            targets.rims,
          )
        : null}
    </>
  );
}

/** While wiring, the pipe being laid is drawn above the glass, on the same route. */
export function PipeConnectionLine({
  fromX,
  fromY,
  toX,
  toY,
  fromPosition,
  toPosition,
}: ConnectionLineComponentProps) {
  const targets = React.useContext(PipeTargetsContext);
  const path = soloPath(
    {
      id: "connection",
      source: ringCentre(fromX, fromY, fromPosition),
      sourceSide: fromPosition,
      target: { x: toX, y: toY },
      targetSide: toPosition,
    },
    targets?.look.corners ?? "sharp",
  );
  return (
    <path
      d={path}
      fill="none"
      strokeWidth={2}
      strokeDasharray="7 5"
      style={{ stroke: tokens.colorAccent }}
    />
  );
}
