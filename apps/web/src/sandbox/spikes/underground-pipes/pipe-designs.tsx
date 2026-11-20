"use client";

import * as React from "react";
import { Position } from "@xyflow/react";

import type { Point } from "./pipe-routing";
import {
  bandsPath,
  chamferPath,
  chevronsPath,
  evenStations,
  pointOnRun,
  routeBends,
  straightRuns,
} from "./pipe-geometry";

/**
 * What a pipe is made of. Every design draws the same route in three places:
 * blurred under the frost (`rest`), sharp where the frost is wiped off it or
 * a well opens onto it, and as the short stub that rises into a recessed
 * well. Designs draw with plain strokes in the type colour; gradients are
 * shared defs, used only inside wells.
 *
 *   tube    the glossy tube the spike started with
 *   fitted  segmented service pipe: cast elbows at the bends, bell couplings
 *           and painted flow arrows along the runs
 *   trace   a flat circuit trace with 45-degree bends
 *   glass   a clear glass tube with coloured fluid in it
 *   fibre   a light pipe whose glow comes through the frost
 *
 * Hovered or selected pipes animate (`flowing`), source to target; nothing
 * else does, so the cost stays with the one pipe being looked at.
 */
export type PipeDesign = "tube" | "fitted" | "trace" | "glass" | "fibre";

export const PIPE_DESIGNS: readonly { value: PipeDesign; label: string }[] = [
  { value: "tube", label: "Tube" },
  { value: "fitted", label: "Fitted" },
  { value: "trace", label: "Trace" },
  { value: "glass", label: "Glass" },
  { value: "fibre", label: "Fibre" },
];

/** Flow-unit width of a tube; the frost wipe is sized from it. */
export const PIPE_WIDTH = 8;
const PIPE_SHINE_WIDTH = 2.5;

const PIPE_CAST_SHADOW_TOP =
  "light-dark(color-mix(in srgb, black 16%, transparent), color-mix(in srgb, black 48%, transparent))";
const PIPE_CAST_SHADOW_MID =
  "light-dark(color-mix(in srgb, black 10%, transparent), color-mix(in srgb, black 30%, transparent))";
/** A pipe's shadow on the floor of a well. */
export const WELL_SHADOW_INK =
  "light-dark(color-mix(in srgb, black 26%, transparent), color-mix(in srgb, black 64%, transparent))";

/** Fitted: where the fittings go, in flow units. */
const FITTED_PITCH = 92;
/** Clear of the well and its frost feather. */
const FITTED_END_CLEAR = 24;
/** How far an elbow's casting runs past the curve on each leg. */
const FITTED_ELBOW_LEG = 4;
const FITTED_COLLAR = 2.4;
const FITTED_BELL = 4.6;
const FITTED_LIP = 1.2;
const FITTED_FLARE = 3.2;
const FITTED_CHEVRON = 3.4;
/** An arrow only fits a gap between fittings at least this long. */
const FITTED_ARROW_GAP = 34;

/** Trace: a flat strip, narrower than a tube, cut 45 degrees at each bend. */
const TRACE_WIDTH = 5.2;
const TRACE_CHAMFER = 10;

const GLASS_WIDTH = 9.4;
const GLASS_FLUID = 4.2;
/** The glass tube's edges: dark on a light floor, bright on a dark one. */
const GLASS_EDGE =
  "light-dark(color-mix(in srgb, black 26%, transparent), color-mix(in srgb, white 30%, transparent))";
const GLASS_WALL =
  "light-dark(color-mix(in srgb, white 80%, transparent), color-mix(in srgb, white 8%, transparent))";
const GLASS_SPECULAR =
  "light-dark(white, color-mix(in srgb, white 78%, transparent))";

const FIBRE_CORE_WIDTH = 2.6;
const FIBRE_HOT =
  "light-dark(color-mix(in srgb, white 88%, transparent), white)";

/** Shared gradient ids for the stub inside a recessed well. */
const PIPE_CYL_H_ID = "pipe-stage-cyl-h";
const PIPE_CYL_V_ID = "pipe-stage-cyl-v";
const PIPE_OVERHANG_RIGHT_ID = "pipe-stage-overhang-right";
const PIPE_OVERHANG_LEFT_ID = "pipe-stage-overhang-left";
const PIPE_OVERHANG_DOWN_ID = "pipe-stage-overhang-down";
const PIPE_OVERHANG_UP_ID = "pipe-stage-overhang-up";
const PIPE_RISER_CROWN_ID = "pipe-stage-riser-crown";

/**
 * Flow animations for hovered and selected pipes. A dash pattern's offset
 * runs from 0 down to minus its period, so the marks travel from the path's
 * start (the source) to its end.
 */
export const PIPE_DESIGN_CSS = `
@keyframes pipe-flow-bubbles { to { stroke-dashoffset: -10; } }
@keyframes pipe-flow-pulse { to { stroke-dashoffset: -210; } }
.pipe-flow-bubbles { animation: pipe-flow-bubbles 0.42s linear infinite; }
.pipe-flow-pulse { animation: pipe-flow-pulse 1.5s linear infinite; }
@media (prefers-reduced-motion: reduce) {
  .pipe-flow-bubbles, .pipe-flow-pulse { animation: none; }
}
`;

type Shadow = "surface" | "middle";

export interface PipeBodyProps {
  design: PipeDesign;
  /** The router's path, with its bends already drawn. */
  path: string;
  /** The route's corner points, when the router has published them. */
  points?: readonly Point[] | undefined;
  color: string;
  /** Radius the router rounds bends with; 0 for square bends. */
  radius: number;
  /** Width multiplier; deeper layers taper slightly, refracted stubs widen. */
  girth?: number;
  /** Cast a soft shadow onto deeper layers crossing underneath this pipe. */
  shadow?: Shadow;
  /** Drawn close and crisp: the pipe is wiped clear of the frost. */
  sharp?: boolean;
  /** Hovered or selected: the design shows what flows, source to target. */
  flowing?: boolean;
}

export function PipeBody(props: PipeBodyProps) {
  switch (props.design) {
    case "tube":
      return <TubeBody {...props} />;
    case "fitted":
      return <FittedBody {...props} />;
    case "trace":
      return <TraceBody {...props} />;
    case "glass":
      return <GlassBody {...props} />;
    case "fibre":
      return <FibreBody {...props} />;
  }
}

function joinFor(radius: number): "miter" | "round" {
  return radius > 0 ? "round" : "miter";
}

function CastShadow({
  path,
  shadow,
  width,
  join,
  opacity,
}: {
  path: string;
  shadow: Shadow | undefined;
  width: number;
  join: "miter" | "round";
  opacity?: number;
}) {
  if (!shadow) return null;
  return (
    <path
      d={path}
      transform="translate(0, 2.2)"
      fill="none"
      strokeWidth={width + 1.2}
      strokeLinejoin={join}
      strokeOpacity={opacity}
      style={{
        stroke:
          shadow === "surface" ? PIPE_CAST_SHADOW_TOP : PIPE_CAST_SHADOW_MID,
      }}
    />
  );
}

/** A tube: optional under-crossing shadow, type colour, and lighter specular shine. */
function TubeBody({
  path,
  color,
  radius,
  girth = 1,
  shadow,
  sharp = false,
}: PipeBodyProps) {
  const join = joinFor(radius);
  return (
    <g>
      <CastShadow
        path={path}
        shadow={shadow}
        width={PIPE_WIDTH * girth}
        join={join}
      />
      {sharp ? (
        <path
          d={path}
          fill="none"
          strokeWidth={PIPE_WIDTH * girth + 0.8}
          strokeLinejoin={join}
          style={{ stroke: `color-mix(in srgb, ${color} 68%, black)` }}
        />
      ) : null}
      <path
        d={path}
        fill="none"
        strokeWidth={PIPE_WIDTH * girth - (sharp ? 0.6 : 0)}
        strokeLinejoin={join}
        style={{ stroke: color }}
      />
      <path
        d={path}
        transform={sharp ? "translate(0, -1.2)" : undefined}
        fill="none"
        strokeWidth={(sharp ? 1.8 : PIPE_SHINE_WIDTH) * girth}
        strokeLinejoin={join}
        style={{
          stroke: sharp
            ? `color-mix(in srgb, ${color} 35%, white)`
            : `color-mix(in srgb, ${color} 45%, white)`,
        }}
      />
    </g>
  );
}

interface Station {
  at: Point;
  dx: number;
  dy: number;
}

/**
 * Where a fitted pipe's castings go: an elbow over every bend with a collar at
 * each end, bell couplings spread along the runs, and a flow arrow in every
 * gap between fittings long enough to hold one. A bell's lip faces upstream,
 * as a bell-and-spigot pipe is laid, so the joints also read as direction.
 */
function fittedParts(points: readonly Point[], radius: number) {
  const elbows: string[] = [];
  const collars: Station[] = [];
  const first = points[0];
  const last = points[points.length - 1];
  const clearOfPorts = (at: Point) =>
    [first, last].every(
      (port) =>
        !port ||
        Math.hypot(at.x - port.x, at.y - port.y) > FITTED_END_CLEAR - 6,
    );
  for (const { corner, inward, outward, reach } of routeBends(points, radius)) {
    const leg = reach + FITTED_ELBOW_LEG;
    const start = {
      x: corner.x - inward.dx * leg,
      y: corner.y - inward.dy * leg,
    };
    const end = {
      x: corner.x + outward.dx * leg,
      y: corner.y + outward.dy * leg,
    };
    const curve =
      reach >= 0.5
        ? `L${corner.x - inward.dx * reach},${corner.y - inward.dy * reach} Q${corner.x},${corner.y} ${corner.x + outward.dx * reach},${corner.y + outward.dy * reach}`
        : `L${corner.x},${corner.y}`;
    elbows.push(`M${start.x},${start.y} ${curve} L${end.x},${end.y}`);
    if (clearOfPorts(start)) collars.push({ at: start, ...inward });
    if (clearOfPorts(end)) collars.push({ at: end, ...outward });
  }

  const bells: Station[] = [];
  const lips: Station[] = [];
  const arrows: Station[] = [];
  const runs = straightRuns(points, {
    endClear: FITTED_END_CLEAR,
    cornerClear: radius + FITTED_ELBOW_LEG + FITTED_COLLAR + 4,
  });
  for (const run of runs) {
    const { dx, dy } = run;
    const offsets = evenStations(run.length, FITTED_PITCH);
    for (const offset of offsets) {
      bells.push({ at: pointOnRun(run, offset), dx, dy });
      // The lip sits on the bell's upstream edge.
      lips.push({
        at: pointOnRun(run, offset - FITTED_BELL / 2 + FITTED_LIP / 2),
        dx,
        dy,
      });
    }
    const marks = [0, ...offsets, run.length];
    for (let index = 1; index < marks.length; index += 1) {
      const before = marks[index - 1] ?? 0;
      const after = marks[index] ?? 0;
      if (after - before < FITTED_ARROW_GAP) continue;
      arrows.push({ at: pointOnRun(run, (before + after) / 2), dx, dy });
    }
  }
  return {
    elbows: elbows.join(" "),
    collars: bandsPath(collars, FITTED_COLLAR),
    bells: bandsPath(bells, FITTED_BELL),
    lips: bandsPath(lips, FITTED_LIP),
    arrows: chevronsPath(arrows, FITTED_CHEVRON),
  };
}

function FittedBody({
  path,
  points,
  color,
  radius,
  girth = 1,
  shadow,
  sharp = false,
}: PipeBodyProps) {
  const join = joinFor(radius);
  const width = PIPE_WIDTH * girth;
  const parts = React.useMemo(
    () => (points ? fittedParts(points, radius) : null),
    [points, radius],
  );
  const casting = `color-mix(in srgb, ${color} 70%, black)`;
  const shine = `translate(${-1.3 * girth}, ${-1.3 * girth})`;
  return (
    <g>
      <CastShadow path={path} shadow={shadow} width={width + 1} join={join} />
      {sharp ? (
        <path
          d={path}
          fill="none"
          strokeWidth={width + 0.8}
          strokeLinejoin={join}
          style={{ stroke: casting }}
        />
      ) : null}
      <path
        d={path}
        fill="none"
        strokeWidth={width - (sharp ? 0.6 : 0)}
        strokeLinejoin={join}
        style={{ stroke: color }}
      />
      {parts ? (
        <path
          d={parts.elbows}
          fill="none"
          strokeWidth={width + 1.8}
          strokeLinejoin={join}
          style={{ stroke: casting }}
        />
      ) : null}
      <path
        d={path}
        transform={shine}
        fill="none"
        strokeWidth={1.5 * girth}
        strokeLinejoin={join}
        style={{ stroke: `color-mix(in srgb, ${color} 50%, white)` }}
      />
      {parts ? (
        <>
          <path
            d={`${parts.collars} ${parts.bells}`}
            fill="none"
            strokeWidth={width + FITTED_FLARE}
            style={{ stroke: casting }}
          />
          <path
            d={parts.lips}
            fill="none"
            strokeWidth={width + FITTED_FLARE}
            style={{ stroke: `color-mix(in srgb, ${color} 55%, white)` }}
          />
          <path
            d={parts.arrows}
            fill="none"
            strokeWidth={1.2 * girth}
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeOpacity={sharp ? 1 : 0.85}
            style={{ stroke: `color-mix(in srgb, ${color} 25%, white)` }}
          />
        </>
      ) : null}
    </g>
  );
}

/** A flat trace: crisp edge, flat fill, no shine and no shadow. */
function TraceBody({
  path,
  points,
  color,
  radius,
  girth = 1,
  flowing = false,
}: PipeBodyProps) {
  const d = React.useMemo(
    () => (points && radius > 0 ? chamferPath(points, TRACE_CHAMFER) : path),
    [path, points, radius],
  );
  const width = TRACE_WIDTH * girth;
  return (
    <g>
      <path
        d={d}
        fill="none"
        strokeWidth={width + 1.4 * girth}
        strokeLinejoin="miter"
        style={{
          stroke: `light-dark(color-mix(in srgb, ${color} 72%, black), color-mix(in srgb, ${color} 62%, white))`,
        }}
      />
      <path
        d={d}
        fill="none"
        strokeWidth={width}
        strokeLinejoin="miter"
        style={{ stroke: color }}
      />
      {flowing ? (
        <path
          d={d}
          className="pipe-flow-pulse"
          fill="none"
          strokeWidth={width - 1.6}
          strokeDasharray="14 196"
          strokeLinecap="round"
          style={{ stroke: `color-mix(in srgb, ${color} 30%, white)` }}
        />
      ) : null}
    </g>
  );
}

/** A clear glass tube: edged wall, coloured fluid, a reflection on the wall. */
function GlassBody({
  path,
  color,
  radius,
  girth = 1,
  shadow,
  flowing = false,
}: PipeBodyProps) {
  const join = joinFor(radius);
  const width = GLASS_WIDTH * girth;
  return (
    <g>
      <CastShadow
        path={path}
        shadow={shadow}
        width={width}
        join={join}
        opacity={0.55}
      />
      <path
        d={path}
        fill="none"
        strokeWidth={width}
        strokeLinejoin={join}
        style={{ stroke: GLASS_EDGE }}
      />
      <path
        d={path}
        fill="none"
        strokeWidth={width - 1.5 * girth}
        strokeLinejoin={join}
        style={{ stroke: GLASS_WALL }}
      />
      <path
        d={path}
        fill="none"
        strokeWidth={GLASS_FLUID * girth}
        strokeLinejoin={join}
        style={{ stroke: color }}
      />
      <path
        d={path}
        transform={`translate(${-0.8 * girth}, ${-0.8 * girth})`}
        fill="none"
        strokeWidth={1.1 * girth}
        strokeLinejoin={join}
        style={{ stroke: `color-mix(in srgb, ${color} 40%, white)` }}
      />
      {flowing ? (
        <path
          d={path}
          className="pipe-flow-bubbles"
          fill="none"
          strokeWidth={1.7 * girth}
          strokeDasharray="0 10"
          strokeLinecap="round"
          strokeLinejoin={join}
          style={{ stroke: `color-mix(in srgb, ${color} 15%, white)` }}
        />
      ) : null}
      <path
        d={path}
        transform={`translate(${-3.1 * girth}, ${-3.1 * girth})`}
        fill="none"
        strokeWidth={0.9 * girth}
        strokeLinejoin={join}
        style={{ stroke: GLASS_SPECULAR }}
      />
    </g>
  );
}

/** A light pipe: a bright core in a soft bloom of its colour. */
function FibreBody({
  path,
  color,
  radius,
  girth = 1,
  flowing = false,
}: PipeBodyProps) {
  const join = joinFor(radius);
  return (
    <g>
      <path
        d={path}
        fill="none"
        strokeWidth={15 * girth}
        strokeLinejoin="round"
        strokeLinecap="round"
        strokeOpacity={0.13}
        style={{ stroke: color }}
      />
      <path
        d={path}
        fill="none"
        strokeWidth={7.5 * girth}
        strokeLinejoin="round"
        strokeLinecap="round"
        strokeOpacity={0.3}
        style={{ stroke: color }}
      />
      <path
        d={path}
        fill="none"
        strokeWidth={FIBRE_CORE_WIDTH * girth}
        strokeLinejoin={join}
        style={{
          stroke: `light-dark(color-mix(in srgb, ${color} 85%, white), color-mix(in srgb, ${color} 40%, white))`,
        }}
      />
      <path
        d={path}
        fill="none"
        strokeWidth={0.9 * girth}
        strokeLinejoin={join}
        style={{ stroke: FIBRE_HOT }}
      />
      {flowing ? (
        <path
          d={path}
          className="pipe-flow-pulse"
          fill="none"
          strokeWidth={4.4 * girth}
          strokeDasharray="18 192"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ stroke: FIBRE_HOT }}
        />
      ) : null}
    </g>
  );
}

/**
 * Filled strip for the pipe stub inside a recessed well: rounded around the
 * port centre and trimmed flush with the circular inner bore wall of radius
 * `boreRadius`. No rectangular corner pokes into the glass wall, and the
 * non-zero bounding box keeps cylindrical and overhang gradients working on
 * both horizontal and vertical stubs.
 */
function stubBodyPath(
  centre: Point,
  position: Position,
  boreRadius: number,
  halfWidth: number,
): string {
  const { x: cx, y: cy } = centre;
  const r = halfWidth;
  const R = boreRadius;
  const reach = Math.sqrt(Math.max(0, R * R - r * r));
  switch (position) {
    case Position.Right:
      return `M${cx},${cy - r} H${(cx + reach).toFixed(2)} A${R},${R} 0 0 1 ${(cx + reach).toFixed(2)},${cy + r} H${cx} A${r},${r} 0 0 1 ${cx},${cy - r} Z`;
    case Position.Left:
      return `M${cx},${cy - r} H${(cx - reach).toFixed(2)} A${R},${R} 0 0 0 ${(cx - reach).toFixed(2)},${cy + r} H${cx} A${r},${r} 0 0 0 ${cx},${cy - r} Z`;
    case Position.Bottom:
      return `M${cx - r},${cy} V${(cy + reach).toFixed(2)} A${R},${R} 0 0 0 ${cx + r},${(cy + reach).toFixed(2)} V${cy} A${r},${r} 0 0 0 ${cx - r},${cy} Z`;
    case Position.Top:
      return `M${cx - r},${cy} V${(cy - reach).toFixed(2)} A${R},${R} 0 0 1 ${cx + r},${(cy - reach).toFixed(2)} V${cy} A${r},${r} 0 0 1 ${cx - r},${cy} Z`;
  }
}

function overhangGradientId(position: Position): string {
  switch (position) {
    case Position.Right:
      return PIPE_OVERHANG_RIGHT_ID;
    case Position.Left:
      return PIPE_OVERHANG_LEFT_ID;
    case Position.Bottom:
      return PIPE_OVERHANG_DOWN_ID;
    case Position.Top:
      return PIPE_OVERHANG_UP_ID;
  }
}

/**
 * The pipe inside a recessed well, from the floor up: its shadow, the stub
 * coming in under the glass wall, and the riser turning straight up into the
 * port. Lighting stays overhead top-left whichever side the pipe enters from.
 */
export function WellStub({
  design,
  centre,
  position,
  color,
  sequence,
  bore,
  prefix,
}: {
  design: PipeDesign;
  centre: Point;
  position: Position;
  color: string;
  sequence: boolean;
  /** Radius of the well's bore. */
  bore: number;
  /** Gradient id prefix of the layer the well is drawn in. */
  prefix: string;
}) {
  const horizontal = position === Position.Left || position === Position.Right;
  const cylinder = `url(#${prefix}${horizontal ? PIPE_CYL_H_ID : PIPE_CYL_V_ID})`;
  const overhang = `url(#${prefix}${overhangGradientId(position)})`;
  const crown = `url(#${prefix}${PIPE_RISER_CROWN_ID})`;
  const strip = (halfWidth: number) =>
    stubBodyPath(centre, position, bore + 0.3, halfWidth);
  const shadowStrip = (halfWidth: number) =>
    stubBodyPath(
      { x: centre.x + 0.4, y: centre.y + 2 },
      position,
      bore - 1.2,
      halfWidth - 0.3,
    );
  const riser = sequence ? 6.2 : 5.6;
  const riserShadow = (radius: number) => (
    <circle
      cx={centre.x + 0.5}
      cy={centre.y + 2.2}
      r={radius}
      style={{ fill: WELL_SHADOW_INK }}
    />
  );

  switch (design) {
    case "tube":
    case "fitted": {
      const stub = strip(PIPE_WIDTH / 2);
      // A fitted pipe turns up through a cast elbow, wider than the pipe.
      const elbow = design === "fitted" ? riser + 1 : riser;
      return (
        <g>
          <path
            d={shadowStrip(PIPE_WIDTH / 2)}
            style={{ fill: WELL_SHADOW_INK }}
          />
          {riserShadow(elbow)}
          <path d={stub} style={{ fill: color }} />
          <path d={stub} fill={cylinder} />
          <path d={stub} fill={overhang} />
          <circle
            cx={centre.x}
            cy={centre.y}
            r={elbow}
            style={{
              fill:
                design === "fitted"
                  ? `color-mix(in srgb, ${color} 70%, black)`
                  : color,
            }}
          />
          <circle cx={centre.x} cy={centre.y} r={elbow} fill={crown} />
        </g>
      );
    }
    case "trace": {
      // Flat on the floor: no shadow. It ends in a plated via.
      const stub = strip(TRACE_WIDTH / 2);
      return (
        <g>
          <path
            d={strip(TRACE_WIDTH / 2 + 0.7)}
            style={{
              fill: `light-dark(color-mix(in srgb, ${color} 72%, black), color-mix(in srgb, ${color} 62%, white))`,
            }}
          />
          <path d={stub} style={{ fill: color }} />
          <path d={stub} fill={overhang} />
          <circle
            cx={centre.x}
            cy={centre.y}
            r={riser + 0.6}
            style={{ fill: color }}
          />
        </g>
      );
    }
    case "glass": {
      const wall = strip(GLASS_WIDTH / 2);
      const fluid = strip(GLASS_FLUID / 2);
      return (
        <g>
          <path
            d={shadowStrip(GLASS_WIDTH / 2)}
            fillOpacity={0.55}
            style={{ fill: WELL_SHADOW_INK }}
          />
          {riserShadow(riser)}
          <path
            d={wall}
            strokeWidth={0.7}
            style={{ fill: GLASS_WALL, stroke: GLASS_EDGE }}
          />
          <path d={fluid} style={{ fill: color }} />
          <path d={fluid} fill={cylinder} />
          <path d={wall} fill={overhang} />
          <circle
            cx={centre.x}
            cy={centre.y}
            r={riser}
            strokeWidth={0.7}
            style={{ fill: GLASS_WALL, stroke: GLASS_EDGE }}
          />
          <circle
            cx={centre.x}
            cy={centre.y}
            r={riser - 2.2}
            style={{ fill: color }}
          />
          <circle cx={centre.x} cy={centre.y} r={riser} fill={crown} />
        </g>
      );
    }
    case "fibre": {
      const glow = strip(4.6);
      return (
        <g>
          <path d={glow} fillOpacity={0.32} style={{ fill: color }} />
          <path d={strip(FIBRE_CORE_WIDTH / 2)} style={{ fill: FIBRE_HOT }} />
          <path d={glow} fill={overhang} />
          <circle
            cx={centre.x}
            cy={centre.y}
            r={riser + 1.6}
            fillOpacity={0.4}
            style={{ fill: color }}
          />
          <circle
            cx={centre.x}
            cy={centre.y}
            r={riser - 2.4}
            style={{ fill: FIBRE_HOT }}
          />
        </g>
      );
    }
  }
}

/** Gradients the in-well stubs share, per layer (`prefix`). */
export function PipeDesignDefs({ prefix }: { prefix: string }) {
  return (
    <>
      {/* Cylindrical shading for horizontal & vertical pipe stubs inside
          a well: off-center top highlight, rounded dark underside. */}
      <linearGradient id={prefix + PIPE_CYL_H_ID} x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor="black" stopOpacity={0.16} />
        <stop offset="22%" stopColor="white" stopOpacity={0.52} />
        <stop offset="48%" stopColor="white" stopOpacity={0} />
        <stop offset="78%" stopColor="black" stopOpacity={0.22} />
        <stop offset="100%" stopColor="black" stopOpacity={0.42} />
      </linearGradient>
      <linearGradient id={prefix + PIPE_CYL_V_ID} x1="0" y1="0" x2="1" y2="0">
        <stop offset="0%" stopColor="black" stopOpacity={0.16} />
        <stop offset="24%" stopColor="white" stopOpacity={0.48} />
        <stop offset="50%" stopColor="white" stopOpacity={0} />
        <stop offset="80%" stopColor="black" stopOpacity={0.22} />
        <stop offset="100%" stopColor="black" stopOpacity={0.4} />
      </linearGradient>
      {/* Glass overhang shadow where the deep pipe emerges from beneath
          the bore wall, brightening as it approaches the vertical riser. */}
      <linearGradient
        id={prefix + PIPE_OVERHANG_RIGHT_ID}
        x1="0"
        y1="0"
        x2="1"
        y2="0"
      >
        <stop offset="0%" stopColor="black" stopOpacity={0} />
        <stop offset="58%" stopColor="black" stopOpacity={0.04} />
        <stop offset="100%" stopColor="black" stopOpacity={0.42} />
      </linearGradient>
      <linearGradient
        id={prefix + PIPE_OVERHANG_LEFT_ID}
        x1="1"
        y1="0"
        x2="0"
        y2="0"
      >
        <stop offset="0%" stopColor="black" stopOpacity={0} />
        <stop offset="58%" stopColor="black" stopOpacity={0.04} />
        <stop offset="100%" stopColor="black" stopOpacity={0.42} />
      </linearGradient>
      <linearGradient
        id={prefix + PIPE_OVERHANG_DOWN_ID}
        x1="0"
        y1="0"
        x2="0"
        y2="1"
      >
        <stop offset="0%" stopColor="black" stopOpacity={0} />
        <stop offset="58%" stopColor="black" stopOpacity={0.04} />
        <stop offset="100%" stopColor="black" stopOpacity={0.42} />
      </linearGradient>
      <linearGradient
        id={prefix + PIPE_OVERHANG_UP_ID}
        x1="0"
        y1="1"
        x2="0"
        y2="0"
      >
        <stop offset="0%" stopColor="black" stopOpacity={0} />
        <stop offset="58%" stopColor="black" stopOpacity={0.04} />
        <stop offset="100%" stopColor="black" stopOpacity={0.42} />
      </linearGradient>
      {/* Top-down vertical riser crown: curved shoulder catching overhead
          top-left light as the pipe rises straight up into the port. */}
      <radialGradient
        id={prefix + PIPE_RISER_CROWN_ID}
        cx="34%"
        cy="30%"
        r="70%"
      >
        <stop offset="0%" stopColor="white" stopOpacity={0.56} />
        <stop offset="45%" stopColor="white" stopOpacity={0.06} />
        <stop offset="78%" stopColor="black" stopOpacity={0.18} />
        <stop offset="100%" stopColor="black" stopOpacity={0.44} />
      </radialGradient>
    </>
  );
}
