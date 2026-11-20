"use client";

import * as React from "react";

import { tokens } from "@/lib/stylex/tokens.stylex";

export type PipeFamily = "glass" | "fibre";
/** Which design pass draws the pipes or the connectors. */
export type DesignPass = "sol" | "opus";
/** A pipe family as one design pass draws it. */
export type PipeDesign = PipeFamily | `${PipeFamily}-opus`;

export const PIPE_FAMILIES = [
  { value: "glass", label: "Glass" },
  { value: "fibre", label: "Fibre" },
] satisfies { value: PipeFamily; label: string }[];

export const DESIGN_PASSES = [
  { value: "sol", label: "Sol" },
  { value: "opus", label: "Opus" },
] satisfies { value: DesignPass; label: string }[];

export function pipeDesign(family: PipeFamily, pass: DesignPass): PipeDesign {
  return pass === "opus" ? `${family}-opus` : family;
}

export const PIPE_WIDTH = 8;

/** The surface the pipes lie on, under the glass. */
export const FLOOR = `light-dark(color-mix(in srgb, ${tokens.colorBg} 88%, black), color-mix(in srgb, ${tokens.colorBg} 35%, black))`;

interface PipeBodyProps {
  design: PipeDesign;
  path: string;
  /** The second strand of a List[T] pipe; `path` is then the first. */
  twin?: string;
  /** The line between the two strands of a List[T] pipe. */
  centre?: string;
  color: string;
  girth?: number;
  sharp?: boolean;
}

export function PipeBody(props: PipeBodyProps) {
  if (props.design === "glass-opus") return <OpusGlass {...props} />;
  if (props.design === "fibre-opus") return <OpusFibre {...props} />;
  return <SolPipe {...props} />;
}

function SolPipe({
  design,
  path,
  twin,
  color,
  girth = 1,
  sharp = false,
}: PipeBodyProps) {
  const glass = design === "glass";
  const width = twin ? (glass ? 2.8 : 2.4) : glass ? PIPE_WIDTH : 4.4;
  const body = glass
    ? `light-dark(color-mix(in oklab, ${color} 80%, #202532), color-mix(in oklab, ${color} 88%, white))`
    : `light-dark(color-mix(in oklab, ${color} 72%, #171c28), color-mix(in oklab, ${color} 75%, white))`;
  const strands = twin ? `${path} ${twin}` : path;
  return (
    <g
      data-strands={twin ? 2 : 1}
      fill="none"
      strokeLinejoin="round"
      strokeLinecap="round"
    >
      <path d={strands} strokeWidth={width * girth} style={{ stroke: body }} />
      {sharp && (
        <path
          d={strands}
          strokeWidth={(glass && !twin ? 2.5 : 0.9) * girth}
          style={{ stroke: `color-mix(in oklab, ${color} 58%, white)` }}
        />
      )}
    </g>
  );
}

/*
 * The Opus pass. Seen through the frost, a pipe is mostly a coloured line on
 * a softer band, so each design is one strong core (two for a List[T] pipe)
 * and a quiet surround that gives the family its character. The cores carry
 * the reading: one line is a T, two lines are a List[T].
 */

/** Sheath widths, single then List[T]. The list sheath holds both cores. */
const GLASS_SHEATH = [8, 10.4] as const;
const GLASS_WALL = 0.65;
const GLASS_CORE = [2.7, 2.1] as const;

/**
 * The colour mixed into the floor, by percent on a light and a dark sheet. The
 * dark frost swallows more, so the dark sheet takes more colour.
 */
function tint(color: string, light: number, dark: number): string {
  return `light-dark(color-mix(in oklab, ${color} ${light}%, ${FLOOR}), color-mix(in oklab, ${color} ${dark}%, ${FLOOR}))`;
}

/**
 * A clear tube carrying coloured liquid: a faintly tinted sheath with a fine
 * wall, and the liquid as a solid core. A List[T] tube carries two cores.
 */
function OpusGlass({ path, twin, centre, color, girth = 1 }: PipeBodyProps) {
  const list = twin !== undefined;
  const sheath = (list ? GLASS_SHEATH[1] : GLASS_SHEATH[0]) * girth;
  const core = (list ? GLASS_CORE[1] : GLASS_CORE[0]) * girth;
  const axis = list ? (centre ?? path) : path;
  const cores = list ? `${path} ${twin}` : path;
  // A dark core on a light sheet, a lit one on a dark sheet.
  const liquid = `light-dark(color-mix(in oklab, ${color} 88%, black), color-mix(in oklab, ${color} 78%, white))`;
  return (
    <g
      data-strands={list ? 2 : 1}
      fill="none"
      strokeLinejoin="round"
      strokeLinecap="round"
    >
      <path
        d={axis}
        strokeWidth={sheath}
        style={{ stroke: tint(color, 46, 62) }}
      />
      <path
        d={axis}
        strokeWidth={sheath - GLASS_WALL * 2 * girth}
        style={{ stroke: tint(color, 20, 36) }}
      />
      <path d={cores} strokeWidth={core} style={{ stroke: liquid }} />
    </g>
  );
}

/**
 * A light guide: a thin hot core in a soft glow, with no walls at all. The
 * glow is a few stacked translucent strokes, so it costs no filter.
 */
function OpusFibre({ path, twin, centre, color, girth = 1 }: PipeBodyProps) {
  const list = twin !== undefined;
  const axis = list ? (centre ?? path) : path;
  const cores = list ? `${path} ${twin}` : path;
  const spread = list ? 2.6 : 0;
  const hot = `light-dark(color-mix(in oklab, ${color} 80%, black), color-mix(in oklab, ${color} 45%, white))`;
  return (
    <g
      data-strands={list ? 2 : 1}
      fill="none"
      strokeLinejoin="round"
      strokeLinecap="round"
    >
      <path
        d={axis}
        strokeWidth={(10 + spread) * girth}
        strokeOpacity={0.14}
        style={{ stroke: color }}
      />
      <path
        d={axis}
        strokeWidth={(6 + spread) * girth}
        strokeOpacity={0.26}
        style={{ stroke: color }}
      />
      <path
        d={cores}
        strokeWidth={(list ? 2.3 : 3) * girth}
        strokeOpacity={0.75}
        style={{ stroke: color }}
      />
      <path
        d={cores}
        strokeWidth={(list ? 1 : 1.3) * girth}
        style={{ stroke: hot }}
      />
    </g>
  );
}
