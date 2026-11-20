"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";

import { tokens } from "@/lib/stylex/tokens.stylex";
import {
  ConnectorFitting,
  FLOOR,
  PIPE_WIDTH,
  PipeBody,
  pipeDesign,
  type PipeDesign,
  type PipeFamily,
} from "./pipe-visuals";
import { pipePath, twinPaths, type Point } from "./pipe-path";

/**
 * The cell canvas's glass stage: the floor, the pipes lying on it, a frosted
 * sheet with a well bored wherever a pipe rises to a port, and the planes the
 * cards' drag and wiring draw into. It is the stage of
 * `../underground-pipes/pipe-layers.tsx` without React Flow: the caller hands
 * it routed pipes and placed wells, already split into resting and moving.
 *
 * Planes, bottom to top (cards sit at z-index 4):
 *   1. floor, then the pipe layers deepest first, then the moving pipes
 *   2. the frosted sheet with the resting wells cut out of it
 *   3. the moving wells drawn over the frost, then the pipe hit targets
 *   5. the pipe being wired, above the cards
 *
 * Cost model: a drag frame changes only the moving pipes and wells. Every
 * resting plane is a memoised component whose props hold no moving data, and
 * its contents are memoised apart from its transform, so neither a drag frame
 * nor a pan reconciles the resting pipes and wells.
 */

export type CellGlassMaterial = "frost" | "liquid";
export type CellWellStyle = "recessed" | "flat";
export type CellCorners = "rounded" | "sharp";
export type WellDirection = "left" | "right" | "top" | "bottom";

export interface CellGlassLook {
  material: CellGlassMaterial;
  well: CellWellStyle;
  pipe: PipeFamily;
  corners: CellCorners;
  /** Blur of a pipe seen through the glass, in flow units. */
  blur: number;
  /** How milky the glass is, 0 (clear) to 1 (opaque). */
  frost: number;
  /** Hairlines on the floor, one per cell. */
  grid: boolean;
}

export interface StageViewport {
  x: number;
  y: number;
  zoom: number;
}

export interface StagePipe {
  id: string;
  points: readonly Point[];
  color: string;
  /** A List[T] pipe, drawn as two strands. */
  sequence: boolean;
  /** 0 is just under the glass; 1 and 2 lie deeper. */
  depth: number;
}

export interface StageWell {
  key: string;
  centre: Point;
  /** The way the pipe leaves the well. */
  exit: WellDirection;
  pipeColor: string;
  portColor: string;
  portSequence: boolean;
  pipeTwin: boolean;
}

export interface LiveConnectionPreview {
  points: readonly Point[];
  color: string;
  sequence: boolean;
  cursor: Point;
}

export interface CellGlassStageProps {
  viewport: StageViewport;
  look: CellGlassLook;
  restingPipes: readonly StagePipe[];
  restingWells: readonly StageWell[];
  movingPipes: readonly StagePipe[];
  movingWells: readonly StageWell[];
  wipedPipeId: string | null;
  /** 1 wipes the frost off the pipe, 0.5 thins it, 0 leaves it. */
  wipedIntensity: number;
  connectionPreview: LiveConnectionPreview | null;
  cellSize: number;
  dragging: boolean;
  onPipeHover?: (id: string | null) => void;
  onPipeSelect?: (id: string) => void;
}

const ROUNDED_CORNER_RADIUS = 12;

export function cellCornerRadius(corners: CellCorners): number {
  return corners === "rounded" ? ROUNDED_CORNER_RADIUS : 0;
}

/**
 * Flow-unit geometry. The ring is the product's 10px port mark. A well's
 * 22px outer rim sits inside its 25px port cell, clear of both cell edges.
 */
const WELL_RADIUS = 9.5;
/** Top-down recessed well: open bore, thick glass wall, and feathered bevel. */
const RECESSED_INNER_RADIUS = 8.8;
const RECESSED_OUTER_RADIUS = 11;
const RECESSED_WALL_MID_RADIUS =
  (RECESSED_INNER_RADIUS + RECESSED_OUTER_RADIUS) / 2;
const RECESSED_WALL_THICKNESS = RECESSED_OUTER_RADIUS - RECESSED_INNER_RADIUS;
const RECESSED_FEATHER_RADIUS = 14;
/** Liquid glass (flat mode): the lip around a well that refracts. */
const LENS_RADIUS = 16;
const LENS_ZOOM = 1.4;
/** Half the side of the glass sheet, in flow units: past any reachable pan. */
const SHEET_REACH = 100_000;
const SHEET = {
  x: -SHEET_REACH,
  y: -SHEET_REACH,
  width: SHEET_REACH * 2,
  height: SHEET_REACH * 2,
};
const HIT_WIDTH = 22;
const PREVIEW_OPACITY = 0.85;

/** One stage per page, so fixed ids are unique; none collides with pipe-layers. */
const STAGE_PREFIX = "cell-stage-";
const DRAG_PREFIX = "cell-drag-";
const CELL_WELL_SHAPES_ID = `${STAGE_PREFIX}well-shapes`;
const CELL_FROST_MASK_ID = `${STAGE_PREFIX}frost`;
const CELL_CLEAR_MASK_ID = `${STAGE_PREFIX}clear`;
const CELL_WELL_FROST_CUT_ID = `${STAGE_PREFIX}well-frost-cut`;
const CELL_WELL_SHADE_ID = `${STAGE_PREFIX}well-shade`;
const CELL_LENS_RING_ID = `${STAGE_PREFIX}lens-ring`;
/**
 * Well paints drawn twice: once in the sheet under {@link STAGE_PREFIX} and
 * once in the drag plane under {@link DRAG_PREFIX}. The full id is the prefix
 * followed by one of these.
 */
const CELL_WELL_CAVITY_SHADE_ID = "well-cavity-shade";
const CELL_WELL_EDGE_ID = "well-edge";
const CELL_WELL_SPECULAR_ID = "well-specular";
const CELL_WELL_INNER_SPEC_ID = "well-inner-spec";
const CELL_WELL_WALL_FROST_ID = "well-wall-frost";
const CELL_WELL_WALL_LIQUID_ID = "well-wall-liquid";
const CELL_WELL_MENISCUS_ID = "well-meniscus";

/** The glass edge at the bottom of a well catches the light. */
const WELL_GLINT =
  "light-dark(white, color-mix(in srgb, white 45%, transparent))";
const WELL_INNER_STEP =
  "light-dark(color-mix(in srgb, black 22%, transparent), color-mix(in srgb, black 65%, transparent))";
const WELL_WALL_FROST_TOP =
  "light-dark(color-mix(in srgb, black 26%, transparent), color-mix(in srgb, black 58%, transparent))";
const WELL_WALL_FROST_MID =
  "light-dark(color-mix(in srgb, black 6%, transparent), color-mix(in srgb, white 6%, transparent))";
const WELL_WALL_FROST_LOW =
  "light-dark(color-mix(in srgb, white 60%, transparent), color-mix(in srgb, white 16%, transparent))";
const WELL_WALL_FROST_BOT =
  "light-dark(color-mix(in srgb, white 92%, transparent), color-mix(in srgb, white 34%, transparent))";
const WELL_WALL_LIQUID_TOP =
  "light-dark(color-mix(in srgb, white 48%, transparent), color-mix(in srgb, white 20%, transparent))";
const WELL_WALL_LIQUID_MID =
  "light-dark(color-mix(in srgb, black 16%, transparent), color-mix(in srgb, black 46%, transparent))";
const WELL_WALL_LIQUID_BOT =
  "light-dark(color-mix(in srgb, white 72%, transparent), color-mix(in srgb, white 28%, transparent))";
const WELL_MENISCUS_HI =
  "light-dark(color-mix(in srgb, white 52%, transparent), color-mix(in srgb, white 14%, transparent))";
const WELL_MENISCUS_LO =
  "light-dark(color-mix(in srgb, black 10%, transparent), color-mix(in srgb, black 35%, transparent))";

const CELL_GRID_PATTERN_ID = `${STAGE_PREFIX}grid-pattern`;

/**
 * Per-plane depth cues, as in pipe-layers: moderate blur growth, preserved
 * opacity, gentle perspective narrowing, and subtle overhead light falloff.
 */
const DEPTH_BLUR_STEP = 0.35;
const DEPTH_OPACITY = [1, 0.88, 0.76] as const;
const DEPTH_GIRTH = [1, 0.92, 0.84] as const;
const DEPTH_BRIGHTNESS = [1, 0.94, 0.88] as const;
const DEPTHS_DEEPEST_FIRST = [2, 1, 0] as const;

type Depth = 0 | 1 | 2;

const EXIT_VECTOR: Record<WellDirection, Point> = {
  left: { x: -1, y: 0 },
  right: { x: 1, y: 0 },
  top: { x: 0, y: -1 },
  bottom: { x: 0, y: 1 },
};

const EXIT_ANGLE: Record<WellDirection, number> = {
  right: 0,
  bottom: Math.PI / 2,
  left: Math.PI,
  top: -Math.PI / 2,
};

interface PipePaths {
  path: string;
  twin?: string;
  centre?: string;
}

/** A pipe with its SVG paths worked out once, for every plane that draws it. */
interface DrawnPipe {
  id: string;
  color: string;
  depth: Depth;
  paths: PipePaths;
}

type PipeLayers = readonly [
  readonly DrawnPipe[],
  readonly DrawnPipe[],
  readonly DrawnPipe[],
];

const s = stylex.create({
  floor: {
    position: "absolute",
    inset: 0,
    zIndex: 1,
    pointerEvents: "none",
  },
  floorGrid: {
    position: "absolute",
    inset: 0,
    width: "100%",
    height: "100%",
    pointerEvents: "none",
  },
  // A 1px plane at the flow origin, moved like a viewport. Not 0: an SVG with
  // no width draws nothing, and the global reset caps an SVG at its parent's
  // width.
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
  pipes: { zIndex: 1 },
  glass: { zIndex: 2 },
  movingOver: { zIndex: 3 },
  preview: { zIndex: 5 },
  planeSvg: {
    position: "absolute",
    top: 0,
    left: 0,
    width: "1px",
    height: "1px",
    overflow: "visible",
  },
  // Hit targets need a box the pointer can reach, so this SVG covers the
  // stage and passes every event its paths do not take. Under the cards.
  hitSvg: {
    position: "absolute",
    inset: 0,
    width: "100%",
    height: "100%",
    zIndex: 3,
    overflow: "visible",
    pointerEvents: "none",
  },
  hitPath: {
    cursor: "pointer",
  },
});

function planeTransform(x: number, y: number, zoom: number): string {
  return `translate3d(${x}px, ${y}px, 0) scale(${zoom})`;
}

/**
 * A CSS filter runs in the element's own units, so this blur is in flow units
 * and scales with zoom by itself.
 */
function depthFilter(
  blur: number,
  liquid: boolean,
  depth: Depth,
): string | undefined {
  const filters: string[] = [];
  const depthBlur = blur * (1 + depth * DEPTH_BLUR_STEP);
  if (depthBlur > 0) filters.push(`blur(${depthBlur}px)`);
  const brightness = DEPTH_BRIGHTNESS[depth];
  if (brightness < 1) filters.push(`brightness(${brightness})`);
  // Vibrancy: colour under Apple's glass is boosted rather than washed out.
  if (liquid) filters.push("saturate(1.9)");
  return filters.length > 0 ? filters.join(" ") : undefined;
}

function toDepth(depth: number): Depth {
  if (depth === 1 || depth === 2) return depth;
  return 0;
}

function drawPipes(
  pipes: readonly StagePipe[],
  radius: number,
): readonly DrawnPipe[] {
  return pipes.map((pipe) => ({
    id: pipe.id,
    color: pipe.color,
    depth: toDepth(pipe.depth),
    paths: pipe.sequence
      ? twinPaths(pipe.points, radius)
      : { path: pipePath(pipe.points, radius) },
  }));
}

/** The first straight run of a pipe out of its well, toward its exit. */
function stubPaths(
  centre: Point,
  exit: WellDirection,
  length: number,
  twin: boolean,
): PipePaths {
  const { x, y } = EXIT_VECTOR[exit];
  const points = [
    centre,
    { x: centre.x + x * length, y: centre.y + y * length },
  ];
  return twin ? twinPaths(points, 0) : { path: pipePath(points, 0) };
}

/**
 * Tapered lens-shaped caustic crescent hugging the glass bore wall on the side
 * the pipe passes beneath it. The inner edge traces the circular arc of
 * `innerRadius`; the outer curve swells to `outerRadius` at the exit and
 * pinches to zero-width tips at both ends.
 */
function causticCrescentPath(
  centre: Point,
  exit: WellDirection,
  innerRadius: number,
  outerRadius: number,
  halfAngleDeg: number,
): string {
  const mid = EXIT_ANGLE[exit];
  const half = (halfAngleDeg * Math.PI) / 180;
  const x0 = centre.x + innerRadius * Math.cos(mid - half);
  const y0 = centre.y + innerRadius * Math.sin(mid - half);
  const x1 = centre.x + innerRadius * Math.cos(mid + half);
  const y1 = centre.y + innerRadius * Math.sin(mid + half);
  const outMidX = centre.x + outerRadius * Math.cos(mid);
  const outMidY = centre.y + outerRadius * Math.sin(mid);
  // Quadratic control point computed so t=0.5 hits outerRadius at `mid`.
  const outCtrlX = 2 * outMidX - 0.5 * (x0 + x1);
  const outCtrlY = 2 * outMidY - 0.5 * (y0 + y1);
  return `M${x0.toFixed(2)},${y0.toFixed(2)} Q${outCtrlX.toFixed(2)},${outCtrlY.toFixed(2)} ${x1.toFixed(2)},${y1.toFixed(2)} A${innerRadius},${innerRadius} 0 0 0 ${x0.toFixed(2)},${y0.toFixed(2)} Z`;
}

/** Local id of a flat well's lens mask. */
function lensMaskId(wellKey: string): string {
  return `${STAGE_PREFIX}lens-${wellKey.replace(/[^\w-]/g, "_")}`;
}

function WellGradients({ prefix }: { prefix: string }) {
  return (
    <>
      {/* Deep recessed cavity shadow cast by the overhead glass slab. */}
      <radialGradient
        id={prefix + CELL_WELL_CAVITY_SHADE_ID}
        cx="50%"
        cy="68%"
        r="72%"
      >
        <stop offset="32%" stopColor="black" stopOpacity={0} />
        <stop offset="76%" stopColor="black" stopOpacity={0.22} />
        <stop offset="100%" stopColor="black" stopOpacity={0.5} />
      </radialGradient>
      <linearGradient
        id={prefix + CELL_WELL_EDGE_ID}
        x1="0"
        y1="0"
        x2="0"
        y2="1"
      >
        <stop offset="0%" stopColor="black" stopOpacity={0.4} />
        <stop offset="50%" stopColor="black" stopOpacity={0} />
        <stop
          offset="100%"
          stopOpacity={0.95}
          style={{ stopColor: WELL_GLINT }}
        />
      </linearGradient>
      {/* Frost bore wall thickness: shadowed upper inner wall, diffused
          frosted catchlight along the lower inner wall. */}
      <linearGradient
        id={prefix + CELL_WELL_WALL_FROST_ID}
        x1="0"
        y1="0"
        x2="0"
        y2="1"
      >
        <stop offset="0%" style={{ stopColor: WELL_WALL_FROST_TOP }} />
        <stop offset="44%" style={{ stopColor: WELL_WALL_FROST_MID }} />
        <stop offset="78%" style={{ stopColor: WELL_WALL_FROST_LOW }} />
        <stop offset="100%" style={{ stopColor: WELL_WALL_FROST_BOT }} />
      </linearGradient>
      {/* Liquid glass bore wall: high-contrast crystalline refraction. */}
      <linearGradient
        id={prefix + CELL_WELL_WALL_LIQUID_ID}
        x1="0"
        y1="0"
        x2="1"
        y2="1"
      >
        <stop offset="0%" style={{ stopColor: WELL_WALL_LIQUID_TOP }} />
        <stop offset="45%" style={{ stopColor: WELL_WALL_LIQUID_MID }} />
        <stop offset="100%" style={{ stopColor: WELL_WALL_LIQUID_BOT }} />
      </linearGradient>
      {/* Outer meniscus bevel sheen for liquid glass. */}
      <linearGradient
        id={prefix + CELL_WELL_MENISCUS_ID}
        x1="0"
        y1="0"
        x2="1"
        y2="1"
      >
        <stop offset="0%" style={{ stopColor: WELL_MENISCUS_HI }} />
        <stop offset="45%" stopColor="white" stopOpacity={0} />
        <stop offset="100%" style={{ stopColor: WELL_MENISCUS_LO }} />
      </linearGradient>
      {/* Liquid glass: light from the top left glints on both sides of a
          cut edge. */}
      <linearGradient
        id={prefix + CELL_WELL_SPECULAR_ID}
        x1="0"
        y1="0"
        x2="1"
        y2="1"
      >
        <stop offset="0%" stopColor="white" stopOpacity={0.95} />
        <stop offset="32%" stopColor="white" stopOpacity={0} />
        <stop offset="68%" stopColor="white" stopOpacity={0} />
        <stop offset="100%" stopColor="white" stopOpacity={0.55} />
      </linearGradient>
      {/* Opposing inner-edge bounce specular for thick liquid glass. */}
      <linearGradient
        id={prefix + CELL_WELL_INNER_SPEC_ID}
        x1="0"
        y1="0"
        x2="1"
        y2="1"
      >
        <stop offset="0%" stopColor="black" stopOpacity={0.48} />
        <stop offset="38%" stopColor="black" stopOpacity={0.08} />
        <stop offset="70%" stopColor="white" stopOpacity={0.12} />
        <stop offset="100%" stopColor="white" stopOpacity={0.78} />
      </linearGradient>
    </>
  );
}

/** The drag plane's own copy of the well paints; it never changes. */
const DragGradients = React.memo(function DragGradients() {
  return (
    <defs>
      <WellGradients prefix={DRAG_PREFIX} />
    </defs>
  );
});

/**
 * Top-down recessed well drilled through thick glass. Lighting stays in world
 * space (overhead top-left) whichever way the pipe leaves, so every well reads
 * as a hole in the same sheet. Bottom to top: an optional opaque floor (only
 * while dragged over intact frost), the cavity shadow, the pipe stub, the
 * port's fitting, then the bore wall, its caustic and its rims.
 */
function RecessedWell({
  well,
  liquid,
  design,
  prefix,
  withFloor = false,
}: {
  well: StageWell;
  liquid: boolean;
  design: PipeDesign;
  prefix: string;
  withFloor?: boolean;
}) {
  const { centre, exit } = well;
  return (
    <g data-cell-well={well.key}>
      {withFloor ? (
        <circle
          cx={centre.x}
          cy={centre.y}
          r={RECESSED_INNER_RADIUS}
          style={{ fill: FLOOR }}
        />
      ) : null}
      <circle
        cx={centre.x}
        cy={centre.y}
        r={RECESSED_INNER_RADIUS}
        fill={`url(#${prefix}${CELL_WELL_CAVITY_SHADE_ID})`}
      />
      <PipeBody
        design={design}
        {...stubPaths(centre, exit, RECESSED_INNER_RADIUS - 1, well.pipeTwin)}
        color={well.pipeColor}
        sharp
      />
      <ConnectorFitting
        centre={centre}
        color={well.portColor}
        sequence={well.portSequence}
        design="opus"
      />
      {/* The bore wall lies above the stub, so the pipe visibly passes under
          the slab's thickness. */}
      {liquid ? (
        <circle
          cx={centre.x}
          cy={centre.y}
          r={RECESSED_OUTER_RADIUS + 1.4}
          fill="none"
          strokeWidth={2.4}
          stroke={`url(#${prefix}${CELL_WELL_MENISCUS_ID})`}
        />
      ) : null}
      <circle
        cx={centre.x}
        cy={centre.y}
        r={RECESSED_WALL_MID_RADIUS}
        fill="none"
        strokeWidth={RECESSED_WALL_THICKNESS}
        stroke={`url(#${prefix}${liquid ? CELL_WELL_WALL_LIQUID_ID : CELL_WELL_WALL_FROST_ID})`}
      />
      {/* Liquid glass refraction: the cut wall catches a tapered coloured
          caustic where the pipe passes under the lip. */}
      {liquid ? (
        <>
          <path
            d={causticCrescentPath(
              centre,
              exit,
              RECESSED_INNER_RADIUS,
              RECESSED_OUTER_RADIUS - 0.1,
              38,
            )}
            fillOpacity={0.32}
            style={{ fill: well.pipeColor }}
          />
          <path
            d={causticCrescentPath(
              centre,
              exit,
              RECESSED_INNER_RADIUS + 0.1,
              RECESSED_INNER_RADIUS + 1.5,
              28,
            )}
            fillOpacity={0.6}
            style={{ fill: `color-mix(in srgb, ${well.pipeColor} 35%, white)` }}
          />
        </>
      ) : null}
      {/* Inner bottom step of the glass slab. */}
      <circle
        cx={centre.x}
        cy={centre.y}
        r={RECESSED_INNER_RADIUS}
        fill="none"
        strokeWidth={liquid ? 0.9 : 0.8}
        stroke={
          liquid ? `url(#${prefix}${CELL_WELL_INNER_SPEC_ID})` : undefined
        }
        style={liquid ? undefined : { stroke: WELL_INNER_STEP }}
      />
      {/* Outer top lip of the glass sheet. */}
      <circle
        cx={centre.x}
        cy={centre.y}
        r={RECESSED_OUTER_RADIUS}
        fill="none"
        strokeWidth={liquid ? 1.25 : 1}
        stroke={`url(#${prefix}${liquid ? CELL_WELL_SPECULAR_ID : CELL_WELL_EDGE_ID})`}
      />
    </g>
  );
}

/** The well's cut edge in the glass (flat mode), then the port's fitting. */
function WellRim({ well, liquid }: { well: StageWell; liquid: boolean }) {
  const { centre } = well;
  return (
    <g data-cell-well={well.key}>
      <circle
        cx={centre.x}
        cy={centre.y}
        r={WELL_RADIUS}
        fill={`url(#${CELL_WELL_SHADE_ID})`}
      />
      <circle
        cx={centre.x}
        cy={centre.y}
        r={WELL_RADIUS}
        fill="none"
        strokeWidth={liquid ? 1.5 : 1.25}
        stroke={`url(#${STAGE_PREFIX}${liquid ? CELL_WELL_SPECULAR_ID : CELL_WELL_EDGE_ID})`}
      />
      <ConnectorFitting
        centre={centre}
        color={well.portColor}
        sequence={well.portSequence}
        design="opus"
      />
    </g>
  );
}

/**
 * A flat well drawn on top of the frost instead of cut out of it: the floor
 * showing through and the stub rising in it. Used while a card moves, so the
 * frost mask stays put.
 */
function OpenWell({ well, design }: { well: StageWell; design: PipeDesign }) {
  const { centre } = well;
  return (
    <g data-cell-well={well.key}>
      <circle
        cx={centre.x}
        cy={centre.y}
        r={WELL_RADIUS}
        style={{ fill: FLOOR }}
      />
      <PipeBody
        design={design}
        {...stubPaths(centre, well.exit, WELL_RADIUS, well.pipeTwin)}
        color={well.pipeColor}
        sharp
      />
      <ConnectorFitting
        centre={centre}
        color={well.portColor}
        sequence={well.portSequence}
        design="opus"
      />
    </g>
  );
}

/** One depth layer's pipe bodies; a pan or a drag frame leaves it alone. */
const PipeLayer = React.memo(function PipeLayer({
  pipes,
  design,
  depth,
}: {
  pipes: readonly DrawnPipe[];
  design: PipeDesign;
  depth: Depth;
}) {
  const girth = DEPTH_GIRTH[depth];
  return (
    <g>
      {pipes.map((pipe) => (
        <g key={pipe.id} data-pipe={pipe.id}>
          <PipeBody
            design={design}
            {...pipe.paths}
            color={pipe.color}
            girth={girth}
          />
        </g>
      ))}
    </g>
  );
});

/** The floor and the three resting pipe layers, deepest first. */
const RestingUnderlay = React.memo(function RestingUnderlay({
  x,
  y,
  zoom,
  blur,
  liquid,
  grid,
  cellSize,
  layers,
  design,
}: {
  x: number;
  y: number;
  zoom: number;
  blur: number;
  liquid: boolean;
  grid: boolean;
  cellSize: number;
  layers: PipeLayers;
  design: PipeDesign;
}) {
  const transform = planeTransform(x, y, zoom);
  return (
    <>
      <div
        aria-hidden="true"
        {...stylex.props(s.floor)}
        style={{ backgroundColor: FLOOR }}
      >
        {grid ? (
          <svg {...stylex.props(s.floorGrid)}>
            <defs>
              <pattern
                id={CELL_GRID_PATTERN_ID}
                width={cellSize}
                height={cellSize}
                patternUnits="userSpaceOnUse"
                patternTransform={`translate(${x} ${y}) scale(${zoom})`}
              >
                <path
                  d={`M ${cellSize} 0 L 0 0 0 ${cellSize}`}
                  fill="none"
                  strokeWidth={1}
                  vectorEffect="non-scaling-stroke"
                  style={{ stroke: tokens.colorGrid }}
                />
              </pattern>
            </defs>
            <rect
              width="100%"
              height="100%"
              fill={`url(#${CELL_GRID_PATTERN_ID})`}
            />
          </svg>
        ) : null}
      </div>
      {DEPTHS_DEEPEST_FIRST.map((depth) => (
        <div
          key={depth}
          aria-hidden="true"
          {...stylex.props(s.plane, s.pipes)}
          style={{
            transform,
            filter: depthFilter(blur, liquid, depth),
            opacity: DEPTH_OPACITY[depth],
          }}
        >
          <svg {...stylex.props(s.planeSvg)}>
            <PipeLayer pipes={layers[depth]} design={design} depth={depth} />
          </svg>
        </div>
      ))}
    </>
  );
});

/** Flat wells as holes, in currentColor, for both glass masks. */
const WellHoles = React.memo(function WellHoles({
  wells,
}: {
  wells: readonly StageWell[];
}) {
  return (
    <g>
      {wells.map((well) => (
        <circle
          key={well.key}
          cx={well.centre.x}
          cy={well.centre.y}
          r={WELL_RADIUS}
          fill="currentColor"
        />
      ))}
    </g>
  );
});

/** Recessed wells' feathered bevel, cut into the frost mask. */
const WellFrostCuts = React.memo(function WellFrostCuts({
  wells,
}: {
  wells: readonly StageWell[];
}) {
  return (
    <g>
      {wells.map((well) => (
        <circle
          key={well.key}
          cx={well.centre.x}
          cy={well.centre.y}
          r={RECESSED_FEATHER_RADIUS}
          fill={`url(#${CELL_WELL_FROST_CUT_ID})`}
        />
      ))}
    </g>
  );
});

/** Where each flat well's lip refracts: a ring around it, in flow units. */
const WellLensMasks = React.memo(function WellLensMasks({
  wells,
}: {
  wells: readonly StageWell[];
}) {
  return (
    <>
      {wells.map(({ key, centre }) => (
        <mask
          key={key}
          id={lensMaskId(key)}
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
            fill={`url(#${CELL_LENS_RING_ID})`}
          />
        </mask>
      ))}
    </>
  );
});

/** Sharp stubs seen through flat wells; the clear mask shows only the holes. */
const WellStubs = React.memo(function WellStubs({
  wells,
  design,
}: {
  wells: readonly StageWell[];
  design: PipeDesign;
}) {
  return (
    <g>
      {wells.map((well) => (
        <PipeBody
          key={well.key}
          design={design}
          {...stubPaths(well.centre, well.exit, WELL_RADIUS, well.pipeTwin)}
          color={well.pipeColor}
          sharp
        />
      ))}
    </g>
  );
});

/** Every resting well's art over the sheet: recessed bores or flat rims. */
const WellArt = React.memo(function WellArt({
  wells,
  flat,
  liquid,
  design,
}: {
  wells: readonly StageWell[];
  flat: boolean;
  liquid: boolean;
  design: PipeDesign;
}) {
  if (!flat) {
    return (
      <g>
        {wells.map((well) => (
          <RecessedWell
            key={well.key}
            well={well}
            liquid={liquid}
            design={design}
            prefix={STAGE_PREFIX}
          />
        ))}
      </g>
    );
  }
  return (
    <>
      {/* Under a well's lip lies only its own stub (the first turn is further
          out), so the refraction draws that stub magnified. */}
      {liquid ? (
        <g>
          {wells.map((well) => (
            <g key={well.key} mask={`url(#${lensMaskId(well.key)})`}>
              <PipeBody
                design={design}
                {...stubPaths(
                  well.centre,
                  well.exit,
                  LENS_RADIUS,
                  well.pipeTwin,
                )}
                color={well.pipeColor}
                girth={LENS_ZOOM}
              />
            </g>
          ))}
        </g>
      ) : null}
      <g>
        {wells.map((well) => (
          <WellRim key={well.key} well={well} liquid={liquid} />
        ))}
      </g>
    </>
  );
});

/** The frost wiped off along a pipe: a soft wide band and a firm core. */
function WipeStrokes({ path, intensity }: { path: string; intensity: number }) {
  return (
    <>
      <path
        d={path}
        fill="none"
        stroke="currentColor"
        strokeOpacity={intensity * 0.35}
        strokeWidth={PIPE_WIDTH + 18}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <path
        d={path}
        fill="none"
        stroke="currentColor"
        strokeOpacity={intensity}
        strokeWidth={PIPE_WIDTH + 9}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </>
  );
}

/**
 * The frosted sheet with the resting wells cut out of it. One set of shapes
 * in currentColor (flat holes and the wiped strip) cuts the frost in black and
 * lets the sharp pipes through in white.
 */
const RestingGlassPlane = React.memo(function RestingGlassPlane({
  x,
  y,
  zoom,
  liquid,
  flat,
  frost,
  design,
  pipes,
  wells,
  wipedPipeId,
  wipedIntensity,
}: {
  x: number;
  y: number;
  zoom: number;
  liquid: boolean;
  flat: boolean;
  frost: number;
  design: PipeDesign;
  pipes: readonly DrawnPipe[];
  wells: readonly StageWell[];
  wipedPipeId: string | null;
  wipedIntensity: number;
}) {
  const wiped =
    wipedPipeId !== null && wipedIntensity > 0
      ? pipes.find((pipe) => pipe.id === wipedPipeId)
      : undefined;
  return (
    <div
      aria-hidden="true"
      {...stylex.props(s.plane, s.glass)}
      style={{ transform: planeTransform(x, y, zoom) }}
    >
      <svg {...stylex.props(s.planeSvg)}>
        <defs>
          <g id={CELL_WELL_SHAPES_ID}>
            {flat ? <WellHoles wells={wells} /> : null}
            {wiped ? (
              <WipeStrokes
                path={wiped.paths.centre ?? wiped.paths.path}
                intensity={wipedIntensity}
              />
            ) : null}
          </g>
          {/* Recessed bevel: clear inside the bore, easing softly into full
              frost across the lip. */}
          <radialGradient id={CELL_WELL_FROST_CUT_ID}>
            <stop
              offset={RECESSED_INNER_RADIUS / RECESSED_FEATHER_RADIUS}
              stopColor="black"
              stopOpacity={1}
            />
            <stop
              offset={RECESSED_OUTER_RADIUS / RECESSED_FEATHER_RADIUS}
              stopColor="black"
              stopOpacity={0.55}
            />
            <stop offset="0.9" stopColor="black" stopOpacity={0.14} />
            <stop offset="1" stopColor="black" stopOpacity={0} />
          </radialGradient>
          <mask id={CELL_FROST_MASK_ID} maskUnits="userSpaceOnUse" {...SHEET}>
            <rect {...SHEET} fill="white" />
            <use href={`#${CELL_WELL_SHAPES_ID}`} style={{ color: "black" }} />
            {flat ? null : <WellFrostCuts wells={wells} />}
          </mask>
          <mask id={CELL_CLEAR_MASK_ID} maskUnits="userSpaceOnUse" {...SHEET}>
            <rect {...SHEET} fill="black" />
            <use href={`#${CELL_WELL_SHAPES_ID}`} style={{ color: "white" }} />
          </mask>
          {/* Light from above: the glass shades the top of a flat well and its
              bottom edge glints. */}
          <radialGradient id={CELL_WELL_SHADE_ID} cx="50%" cy="74%" r="74%">
            <stop offset="58%" stopColor="black" stopOpacity={0} />
            <stop offset="100%" stopColor="black" stopOpacity={0.38} />
          </radialGradient>
          <WellGradients prefix={STAGE_PREFIX} />
          {/* The refracting lip (flat mode): clear right at the well's edge,
              fading into the frost further out. */}
          <radialGradient id={CELL_LENS_RING_ID}>
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
          {flat && liquid ? <WellLensMasks wells={wells} /> : null}
        </defs>
        <rect
          {...SHEET}
          mask={`url(#${CELL_FROST_MASK_ID})`}
          fillOpacity={frost}
          style={{ fill: tokens.colorBg }}
        />
        <g mask={`url(#${CELL_CLEAR_MASK_ID})`}>
          {flat ? <WellStubs wells={wells} design={design} /> : null}
          {wiped ? (
            <PipeBody
              design={design}
              {...wiped.paths}
              color={wiped.color}
              sharp
            />
          ) : null}
        </g>
        <WellArt wells={wells} flat={flat} liquid={liquid} design={design} />
      </svg>
    </div>
  );
});

/** Invisible wide strokes along the resting pipes, for hover and select. */
const HitPaths = React.memo(function HitPaths({
  pipes,
  onHover,
  onSelect,
}: {
  pipes: readonly DrawnPipe[];
  onHover: (id: string | null) => void;
  onSelect: (id: string) => void;
}) {
  return (
    <>
      {pipes.map((pipe) => (
        <path
          key={pipe.id}
          data-pipe-hit={pipe.id}
          d={pipe.paths.centre ?? pipe.paths.path}
          fill="none"
          stroke="transparent"
          strokeWidth={HIT_WIDTH}
          {...stylex.props(s.hitPath)}
          onPointerEnter={() => onHover(pipe.id)}
          onPointerLeave={() => onHover(null)}
          onClick={(event) => {
            event.stopPropagation();
            onSelect(pipe.id);
          }}
        />
      ))}
    </>
  );
});

/** Hit targets under the cards, so a card always wins the pointer. */
const PipeHitPlane = React.memo(function PipeHitPlane({
  x,
  y,
  zoom,
  pipes,
  dragging,
  onHover,
  onSelect,
}: {
  x: number;
  y: number;
  zoom: number;
  pipes: readonly DrawnPipe[];
  dragging: boolean;
  onHover: (id: string | null) => void;
  onSelect: (id: string) => void;
}) {
  return (
    <svg aria-hidden="true" {...stylex.props(s.hitSvg)}>
      {/* The paths inherit pointer-events, so a drag switches them off
          without re-rendering them. */}
      <g
        transform={`translate(${x} ${y}) scale(${zoom})`}
        style={{ pointerEvents: dragging ? "none" : "stroke" }}
      >
        <HitPaths pipes={pipes} onHover={onHover} onSelect={onSelect} />
      </g>
    </svg>
  );
});

/** Layers 1 to 3 and the wiring preview of the cell canvas. */
export function CellGlassStage({
  viewport,
  look,
  restingPipes,
  restingWells,
  movingPipes,
  movingWells,
  wipedPipeId,
  wipedIntensity,
  connectionPreview,
  cellSize,
  dragging,
  onPipeHover,
  onPipeSelect,
}: CellGlassStageProps) {
  const { x, y, zoom } = viewport;
  const liquid = look.material === "liquid";
  const flat = look.well === "flat";
  const design = pipeDesign(look.pipe, "opus");
  const radius = cellCornerRadius(look.corners);
  const transform = planeTransform(x, y, zoom);

  // Resting props keep their identity across drag frames, so these do too.
  const restingDrawn = React.useMemo(
    () => drawPipes(restingPipes, radius),
    [restingPipes, radius],
  );
  const restingLayers = React.useMemo<PipeLayers>(
    () => [
      restingDrawn.filter((pipe) => pipe.depth === 0),
      restingDrawn.filter((pipe) => pipe.depth === 1),
      restingDrawn.filter((pipe) => pipe.depth === 2),
    ],
    [restingDrawn],
  );
  const movingDrawn = React.useMemo(
    () => drawPipes(movingPipes, radius),
    [movingPipes, radius],
  );

  // Stable handlers, so a caller's inline callbacks do not re-render the hits.
  const hoverRef = React.useRef(onPipeHover);
  const selectRef = React.useRef(onPipeSelect);
  React.useLayoutEffect(() => {
    hoverRef.current = onPipeHover;
    selectRef.current = onPipeSelect;
  });
  const handleHover = React.useCallback((id: string | null) => {
    hoverRef.current?.(id);
  }, []);
  const handleSelect = React.useCallback((id: string) => {
    selectRef.current?.(id);
  }, []);

  return (
    <>
      <RestingUnderlay
        x={x}
        y={y}
        zoom={zoom}
        blur={look.blur}
        liquid={liquid}
        grid={look.grid}
        cellSize={cellSize}
        layers={restingLayers}
        design={design}
      />
      {/* Pipes of a dragged card, in their own blurred plane under the frost,
          so a drag frame leaves the resting layers alone. */}
      <div
        aria-hidden="true"
        {...stylex.props(s.plane, s.pipes)}
        style={{ transform, filter: depthFilter(look.blur, liquid, 0) }}
      >
        <svg {...stylex.props(s.planeSvg)}>
          {movingDrawn.map((pipe) => (
            <g
              key={pipe.id}
              data-pipe={pipe.id}
              opacity={DEPTH_OPACITY[pipe.depth]}
            >
              <PipeBody
                design={design}
                {...pipe.paths}
                color={pipe.color}
                girth={DEPTH_GIRTH[pipe.depth]}
              />
            </g>
          ))}
        </svg>
      </div>
      <RestingGlassPlane
        x={x}
        y={y}
        zoom={zoom}
        liquid={liquid}
        flat={flat}
        frost={look.frost}
        design={design}
        pipes={restingDrawn}
        wells={restingWells}
        wipedPipeId={wipedPipeId}
        wipedIntensity={wipedIntensity}
      />
      {/* Wells of a dragged card, drawn over the frost so a drag frame leaves
          the sheet's masks and the resting wells untouched. */}
      <div
        aria-hidden="true"
        {...stylex.props(s.plane, s.movingOver)}
        style={{ transform }}
      >
        <svg {...stylex.props(s.planeSvg)}>
          <DragGradients />
          {movingWells.map((well) =>
            flat ? (
              <OpenWell key={well.key} well={well} design={design} />
            ) : (
              <RecessedWell
                key={well.key}
                well={well}
                liquid={liquid}
                design={design}
                prefix={DRAG_PREFIX}
                withFloor
              />
            ),
          )}
        </svg>
      </div>
      <PipeHitPlane
        x={x}
        y={y}
        zoom={zoom}
        pipes={restingDrawn}
        dragging={dragging}
        onHover={handleHover}
        onSelect={handleSelect}
      />
      {connectionPreview ? (
        <div
          aria-hidden="true"
          {...stylex.props(s.plane, s.preview)}
          style={{ transform }}
        >
          <svg {...stylex.props(s.planeSvg)}>
            <g opacity={PREVIEW_OPACITY}>
              <PipeBody
                design={design}
                {...(connectionPreview.sequence
                  ? twinPaths(connectionPreview.points, radius)
                  : { path: pipePath(connectionPreview.points, radius) })}
                color={connectionPreview.color}
                sharp
              />
              <ConnectorFitting
                centre={connectionPreview.cursor}
                color={connectionPreview.color}
                sequence={connectionPreview.sequence}
                design="opus"
              />
            </g>
          </svg>
        </div>
      ) : null}
    </>
  );
}
