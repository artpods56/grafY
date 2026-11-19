"use client";

import * as React from "react";
import { createPortal } from "react-dom";
import * as stylex from "@stylexjs/stylex";
import {
  Position,
  useStore,
  useNodeConnections,
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
 * through it is boosted rather than washed out, the glass wall catches a
 * pipe-tinted edge caustic where a pipe enters, and its cut edges catch a
 * double specular highlight.
 */
export type PipeMaterial = "frost" | "liquid";
/**
 * `recessed` is a top-down bevelled bore showing glass thickness, floor
 * shadow, a cylindrical pipe rising into a vertical shoulder, and a soft
 * optical transition across the lip. `flat` keeps the initial prototype well
 * for direct before/after comparison.
 */
export type PipeWell = "recessed" | "flat";

export interface PipeLook {
  corners: PipeCorners;
  material: PipeMaterial;
  well: PipeWell;
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
/** Top-down recessed well: open bore, thick glass wall, and feathered bevel. */
const RECESSED_INNER_RADIUS = 11.2;
const RECESSED_OUTER_RADIUS = 14;
const RECESSED_WALL_MID_RADIUS =
  (RECESSED_INNER_RADIUS + RECESSED_OUTER_RADIUS) / 2;
const RECESSED_WALL_THICKNESS = RECESSED_OUTER_RADIUS - RECESSED_INNER_RADIUS;
const RECESSED_FEATHER_RADIUS = 18;
/** How far a pipe runs straight out of its well before its first turn. */
const ROUNDED_CORNER_RADIUS = 12;
/** Liquid glass (flat mode): the lip around a well that refracts. */
const LENS_RADIUS = 21;
const LENS_ZOOM = 1.4;
/** Half the side of the glass sheet, in flow units: past any reachable pan. */
const SHEET_REACH = 100_000;

/** One stage per page, so fixed ids are unique. */
const WELL_SHAPES_ID = "pipe-stage-well-shapes";
const FROST_MASK_ID = "pipe-stage-frost";
const CLEAR_MASK_ID = "pipe-stage-clear";
const WELL_FROST_CUT_ID = "pipe-stage-well-frost-cut";
const WELL_SHADE_ID = "pipe-stage-well-shade";
const WELL_CAVITY_SHADE_ID = "pipe-stage-well-cavity-shade";
const WELL_EDGE_ID = "pipe-stage-well-edge";
const WELL_SPECULAR_ID = "pipe-stage-well-specular";
const WELL_INNER_SPEC_ID = "pipe-stage-well-inner-spec";
const WELL_WALL_FROST_ID = "pipe-stage-well-wall-frost";
const WELL_WALL_LIQUID_ID = "pipe-stage-well-wall-liquid";
const WELL_MENISCUS_ID = "pipe-stage-well-meniscus";
const PIPE_CYL_H_ID = "pipe-stage-cyl-h";
const PIPE_CYL_V_ID = "pipe-stage-cyl-v";
const PIPE_OVERHANG_RIGHT_ID = "pipe-stage-overhang-right";
const PIPE_OVERHANG_LEFT_ID = "pipe-stage-overhang-left";
const PIPE_OVERHANG_DOWN_ID = "pipe-stage-overhang-down";
const PIPE_OVERHANG_UP_ID = "pipe-stage-overhang-up";
const PIPE_RISER_CROWN_ID = "pipe-stage-riser-crown";
const PIPE_PORT_SHADOW_ID = "pipe-stage-port-shadow";
const LENS_RING_ID = "pipe-stage-lens-ring";

/** The floor is darker than the glass, so a well reads as a hole. */
const FLOOR = `light-dark(color-mix(in srgb, ${tokens.colorBg} 88%, black), color-mix(in srgb, ${tokens.colorBg} 35%, black))`;
/** The glass edge at the bottom of a well catches the light. */
const WELL_GLINT =
  "light-dark(white, color-mix(in srgb, white 45%, transparent))";
const WELL_SHADOW_INK =
  "light-dark(color-mix(in srgb, black 26%, transparent), color-mix(in srgb, black 64%, transparent))";
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

/**
 * Per-plane depth cues so all three planes stay legible while reading as
 * distinct elevations: moderate blur growth, preserved opacity, gentle
 * perspective narrowing, and subtle overhead light falloff.
 */
const DEPTH_BLUR_STEP = 0.35;
const DEPTH_OPACITY = [1, 0.88, 0.76] as const;
const DEPTH_GIRTH = [1, 0.92, 0.84] as const;
const DEPTH_BRIGHTNESS = [1, 0.94, 0.88] as const;
const PIPE_CAST_SHADOW_TOP =
  "light-dark(color-mix(in srgb, black 16%, transparent), color-mix(in srgb, black 48%, transparent))";
const PIPE_CAST_SHADOW_MID =
  "light-dark(color-mix(in srgb, black 10%, transparent), color-mix(in srgb, black 30%, transparent))";

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
  /** Live laned routes for pipes attached to cards currently being dragged. */
  movingBook: RouteBook;
  /** One blurred group per layer, the surface first. */
  pipes: readonly (SVGGElement | null)[];
  sharp: SVGGElement | null;
  wells: SVGGElement | null;
  frostCuts: SVGGElement | null;
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
  movingOver: { zIndex: 3 },
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

function WellGradients({ prefix = "" }: { prefix?: string }) {
  return (
    <>
      {/* Deep recessed cavity shadow cast by the overhead glass slab. */}
      <radialGradient
        id={prefix + WELL_CAVITY_SHADE_ID}
        cx="50%"
        cy="68%"
        r="72%"
      >
        <stop offset="32%" stopColor="black" stopOpacity={0} />
        <stop offset="76%" stopColor="black" stopOpacity={0.22} />
        <stop offset="100%" stopColor="black" stopOpacity={0.5} />
      </radialGradient>
      <linearGradient id={prefix + WELL_EDGE_ID} x1="0" y1="0" x2="0" y2="1">
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
        id={prefix + WELL_WALL_FROST_ID}
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
        id={prefix + WELL_WALL_LIQUID_ID}
        x1="0"
        y1="0"
        x2="1"
        y2="1"
      >
        <stop offset="0%" style={{ stopColor: WELL_WALL_LIQUID_TOP }} />
        <stop offset="45%" style={{ stopColor: WELL_WALL_LIQUID_MID }} />
        <stop offset="100%" style={{ stopColor: WELL_WALL_LIQUID_BOT }} />
      </linearGradient>
      {/* Outer meniscus bevel sheen for Liquid glass. */}
      <linearGradient
        id={prefix + WELL_MENISCUS_ID}
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
        id={prefix + WELL_SPECULAR_ID}
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
        id={prefix + WELL_INNER_SPEC_ID}
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
      {/* Contact shadow directly beneath the port ring resting on top of
                the rising pipe collar. */}
      <radialGradient id={prefix + PIPE_PORT_SHADOW_ID}>
        <stop offset="55%" stopColor="black" stopOpacity={0.42} />
        <stop offset="82%" stopColor="black" stopOpacity={0.16} />
        <stop offset="100%" stopColor="black" stopOpacity={0} />
      </radialGradient>
    </>
  );
}

const DRAG_GRADIENT_PREFIX = "drag-";

/** Layers 1 to 3. Edges fill them through {@link PipeTargetsProvider}. */
export function GlassStage({
  look,
  onPipes,
  onMiddlePipes,
  onDeepPipes,
  onSharp,
  onWells,
  onFrostCuts,
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
  onFrostCuts: GroupRef;
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
    const brightness = DEPTH_BRIGHTNESS[depth] ?? 1;
    if (brightness < 1) filters.push(`brightness(${brightness})`);
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
      {/* Pipes of a dragged card sit in their own blurred plane under the
          frosted sheet so dragging never invalidates the resting layers. */}
      <div
        aria-hidden="true"
        {...stylex.props(s.plane, s.pipes)}
        style={{ transform: viewport, filter }}
      >
        <svg {...stylex.props(s.planeSvg)}>
          <g ref={onMovingUnder} />
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
            {/* Smooth radial frost bevel cutout for recessed wells: clear
                inside the bore, easing softly into full frost across the lip. */}
            <radialGradient id={WELL_FROST_CUT_ID}>
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
            <mask id={FROST_MASK_ID} maskUnits="userSpaceOnUse" {...sheet}>
              <rect {...sheet} fill="white" />
              <use href={`#${WELL_SHAPES_ID}`} style={{ color: "black" }} />
              <g ref={onFrostCuts} />
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
            <WellGradients />
            {/* The refracting lip (flat mode): clear right at the well's edge,
                fading into the frost further out. */}
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
          <rect
            {...sheet}
            mask={`url(#${FROST_MASK_ID})`}
            fillOpacity={look.frost}
            style={{ fill: tokens.colorBg }}
          />
          <g mask={`url(#${CLEAR_MASK_ID})`}>
            <g ref={onSharp} />
          </g>
          <g ref={onLenses} />
          <g ref={onRims} />
        </svg>
      </div>
      {/* Wells of a dragged card sit above the static glass sheet so drag
          frames leave the whole-sheet frost mask and resting wells untouched. */}
      <div
        aria-hidden="true"
        {...stylex.props(s.plane, s.movingOver)}
        style={{ transform: viewport }}
      >
        <svg {...stylex.props(s.planeSvg)}>
          <defs>
            <WellGradients prefix={DRAG_GRADIENT_PREFIX} />
          </defs>
          <g ref={onMovingOver} />
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

function isSequenceHandle(handleId: string | null | undefined): boolean {
  return decodeHandleId(handleId)?.shape === "many";
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

/**
 * Tapered lens-shaped caustic crescent hugging the glass bore wall on the side
 * the pipe passes beneath it. The inner edge traces the exact circular arc of
 * `innerRadius`, while the outer curve swells to `outerRadius` at the entry
 * centre and pinches cleanly to zero-width tips at both ends.
 */
function causticCrescentPath(
  centre: Point,
  position: Position,
  innerRadius: number,
  outerRadius: number,
  halfAngleDeg: number,
): string {
  const mid = {
    [Position.Right]: 0,
    [Position.Bottom]: Math.PI / 2,
    [Position.Left]: Math.PI,
    [Position.Top]: -Math.PI / 2,
  }[position];
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

const EMPTY_PATHS: ReadonlyMap<string, RoutedPath> = new Map();

function selectPipesByMotion(state: ReactFlowState, moving: boolean): string {
  const requests: PipeRequest[] = [];
  for (const edge of state.edges) {
    if (edge.type !== PIPE_EDGE_TYPE) continue;
    const sourceNode = state.nodeLookup.get(edge.source);
    const targetNode = state.nodeLookup.get(edge.target);
    if (!sourceNode || !targetNode) continue;
    const edgeMoving = Boolean(sourceNode.dragging || targetNode.dragging);
    if (edgeMoving !== moving) continue;
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

/**
 * Every resting pipe's ports, as a string so the router re-runs only when one
 * of them moves. Pipes of a dragged card are left out until it is put down.
 */
function selectRestingPipes(state: ReactFlowState): string {
  return selectPipesByMotion(state, false);
}

/** Only pipes attached to cards currently being dragged. */
function selectMovingPipes(state: ReactFlowState): string {
  return selectPipesByMotion(state, true);
}

/**
 * Routes just the dragging card(s)' pipes together so they stay spread into
 * parallel lanes while moving, without touching any resting pipe or layer.
 */
function MovingPipeRouter({
  book,
  corners,
  lanes,
}: {
  book: RouteBook;
  corners: PipeCorners;
  lanes: boolean;
}) {
  const moving = useStore(selectMovingPipes);
  React.useLayoutEffect(() => {
    const requests = JSON.parse(moving) as PipeRequest[];
    if (requests.length === 0) {
      book.publish(EMPTY_PATHS);
      return;
    }
    const radius = cornerRadius(corners);
    const paths = new Map<string, RoutedPath>();
    for (const [id, routed] of routePipes(requests, { lanes, depth: false })) {
      paths.set(id, {
        path: pipePath(routed.points, radius),
        depth: routed.depth,
      });
    }
    book.publish(paths);
  }, [book, corners, lanes, moving]);
  return null;
}

/** Lays out all resting pipes together and publishes their paths. */
export function PipeRouter({
  book,
  movingBook,
  corners,
  lanes,
  depth,
}: {
  book: RouteBook;
  movingBook: RouteBook;
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
  return <MovingPipeRouter book={movingBook} corners={corners} lanes={lanes} />;
}

const NO_BOOK_SUBSCRIPTION = () => () => {};

/** A tube: optional under-crossing shadow, type colour, and lighter specular shine. */
function PipeBody({
  path,
  color,
  corners,
  girth = 1,
  shadow,
  cylindrical = false,
}: {
  path: string;
  color: string;
  corners: PipeCorners;
  /** Width multiplier; deeper layers taper slightly, refracted stubs widen. */
  girth?: number;
  /** Cast a soft shadow onto deeper layers crossing underneath this pipe. */
  shadow?: "surface" | "middle";
  /** Richer edge casing and off-center highlight for sharp wiped pipes. */
  cylindrical?: boolean;
}) {
  const join = corners === "sharp" ? "miter" : "round";
  return (
    <g>
      {shadow ? (
        <path
          d={path}
          transform="translate(0, 2.2)"
          fill="none"
          strokeWidth={PIPE_WIDTH * girth + 1.2}
          strokeLinejoin={join}
          style={{
            stroke:
              shadow === "surface"
                ? PIPE_CAST_SHADOW_TOP
                : PIPE_CAST_SHADOW_MID,
          }}
        />
      ) : null}
      {cylindrical ? (
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
        strokeWidth={PIPE_WIDTH * girth - (cylindrical ? 0.6 : 0)}
        strokeLinejoin={join}
        style={{ stroke: color }}
      />
      <path
        d={path}
        transform={cylindrical ? "translate(0, -1.2)" : undefined}
        fill="none"
        strokeWidth={(cylindrical ? 1.8 : PIPE_SHINE_WIDTH) * girth}
        strokeLinejoin={join}
        style={{
          stroke: cylindrical
            ? `color-mix(in srgb, ${color} 35%, white)`
            : `color-mix(in srgb, ${color} 45%, white)`,
        }}
      />
    </g>
  );
}

/**
 * Top-down recessed well drilled through thick glass.
 *
 * Lighting stays in world space (overhead top-left) regardless of which side
 * the pipe enters from, so input and output wells read as holes in the same
 * sheet. Layers from bottom to top:
 *   1. optional opaque floor (only while dragging over intact frost)
 *   2. deep cavity shadow under the glass overhang
 *   3. pipe floor cast shadow
 *   4. cylindrical pipe stub emerging from under the bore wall into a
 *      top-down 90° vertical riser collar directly beneath the port ring
 *   5. port ring contact shadow separating the top-plane handle from the shaft
 *   6. thick glass bore wall (translucent frosted or refractive liquid with a
 *      pipe-tinted edge caustic on the entry arc) and specular rims
 */
function RecessedWell({
  centre,
  position,
  color,
  material,
  sequence,
  withFloor = false,
}: {
  centre: Point;
  position: Position;
  color: string;
  material: PipeMaterial;
  sequence: boolean;
  withFloor?: boolean;
}) {
  const prefix = withFloor ? DRAG_GRADIENT_PREFIX : "";
  const liquid = material === "liquid";
  const horizontal = position === Position.Left || position === Position.Right;
  const stub = stubBodyPath(
    centre,
    position,
    RECESSED_INNER_RADIUS + 0.3,
    PIPE_WIDTH / 2,
  );
  const shadowStub = stubBodyPath(
    { x: centre.x + 0.4, y: centre.y + 2 },
    position,
    RECESSED_INNER_RADIUS - 1.2,
    PIPE_WIDTH / 2 - 0.3,
  );
  const cylGrad = horizontal ? PIPE_CYL_H_ID : PIPE_CYL_V_ID;
  const overhangGrad = overhangGradientId(position);
  const riserRadius = sequence ? 6.2 : 5.6;
  const portShadowRadius = sequence ? 9.4 : 6.4;

  return (
    <g>
      {withFloor ? (
        <circle
          cx={centre.x}
          cy={centre.y}
          r={RECESSED_INNER_RADIUS}
          style={{ fill: FLOOR }}
        />
      ) : null}
      {/* Recessed bore floor occlusion under the overhead glass slab. */}
      <circle
        cx={centre.x}
        cy={centre.y}
        r={RECESSED_INNER_RADIUS}
        fill={`url(#${prefix}${WELL_CAVITY_SHADE_ID})`}
      />
      {/* Cast shadow of the horizontal pipe and vertical riser on the floor. */}
      <path d={shadowStub} style={{ fill: WELL_SHADOW_INK }} />
      <circle
        cx={centre.x + 0.5}
        cy={centre.y + 2.2}
        r={riserRadius}
        style={{ fill: WELL_SHADOW_INK }}
      />
      {/* 3D cylindrical pipe stub tucked cleanly under the glass bore wall. */}
      <path d={stub} style={{ fill: color }} />
      <path d={stub} fill={`url(#${prefix}${cylGrad})`} />
      <path d={stub} fill={`url(#${prefix}${overhangGrad})`} />
      {/* Top-down 90° vertical riser shoulder rising straight into the port. */}
      <circle
        cx={centre.x}
        cy={centre.y}
        r={riserRadius}
        style={{ fill: color }}
      />
      <circle
        cx={centre.x}
        cy={centre.y}
        r={riserRadius}
        fill={`url(#${prefix}${PIPE_RISER_CROWN_ID})`}
      />
      {/* Contact shadow immediately under the card's floating port ring. */}
      <circle
        cx={centre.x}
        cy={centre.y + 1.1}
        r={portShadowRadius}
        fill={`url(#${prefix}${PIPE_PORT_SHADOW_ID})`}
      />
      {/* Thick glass bore wall drawn above the stub so the pipe visibly passes
          underneath the glass slab thickness. */}
      {liquid ? (
        <circle
          cx={centre.x}
          cy={centre.y}
          r={RECESSED_OUTER_RADIUS + 1.4}
          fill="none"
          strokeWidth={2.4}
          stroke={`url(#${prefix}${WELL_MENISCUS_ID})`}
        />
      ) : null}
      <circle
        cx={centre.x}
        cy={centre.y}
        r={RECESSED_WALL_MID_RADIUS}
        fill="none"
        strokeWidth={RECESSED_WALL_THICKNESS}
        stroke={`url(#${prefix}${liquid ? WELL_WALL_LIQUID_ID : WELL_WALL_FROST_ID})`}
      />
      {/* Liquid glass internal refraction: the cut glass wall catches a
          tapered coloured caustic right where the pipe passes under the lip. */}
      {liquid ? (
        <>
          <path
            d={causticCrescentPath(
              centre,
              position,
              RECESSED_INNER_RADIUS,
              RECESSED_OUTER_RADIUS - 0.1,
              38,
            )}
            fillOpacity={0.32}
            style={{ fill: color }}
          />
          <path
            d={causticCrescentPath(
              centre,
              position,
              RECESSED_INNER_RADIUS + 0.1,
              RECESSED_INNER_RADIUS + 1.5,
              28,
            )}
            fillOpacity={0.6}
            style={{ fill: `color-mix(in srgb, ${color} 35%, white)` }}
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
        stroke={liquid ? `url(#${prefix}${WELL_INNER_SPEC_ID})` : undefined}
        style={liquid ? undefined : { stroke: WELL_INNER_STEP }}
      />
      {/* Outer top lip of the glass sheet. */}
      <circle
        cx={centre.x}
        cy={centre.y}
        r={RECESSED_OUTER_RADIUS}
        fill="none"
        strokeWidth={liquid ? 1.25 : 1}
        stroke={`url(#${prefix}${liquid ? WELL_SPECULAR_ID : WELL_EDGE_ID})`}
      />
    </g>
  );
}

/** The well's cut edge in the glass (flat mode): shade under top, glint below. */
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

/** A shared port has one bore, and only the card holding it can move it. */
function PortWell({
  edgeId,
  nodeId,
  end,
  handleId,
  moving,
  targets,
  ...well
}: Omit<React.ComponentProps<typeof RecessedWell>, "withFloor"> & {
  edgeId: string;
  nodeId: string;
  end: "source" | "target";
  handleId?: string | null;
  moving: boolean;
  targets: PipeTargets;
}) {
  const connections = useNodeConnections({
    id: nodeId,
    handleType: end,
    handleId: handleId ?? undefined,
  });
  if (connections[0]?.edgeId !== edgeId) return null;
  const layer = moving ? targets.movingOver : targets.rims;
  return (
    <>
      {!moving &&
        targets.frostCuts &&
        createPortal(
          <circle
            cx={well.centre.x}
            cy={well.centre.y}
            r={RECESSED_FEATHER_RADIUS}
            fill={`url(#${WELL_FROST_CUT_ID})`}
          />,
          targets.frostCuts,
        )}
      {layer &&
        createPortal(<RecessedWell {...well} withFloor={moving} />, layer)}
    </>
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
  targetHandleId,
  selected,
}: EdgeProps<PipeEdge>) {
  const targets = React.useContext(PipeTargetsContext);
  const [hovered, setHovered] = React.useState(false);
  const sourceMoving = useStore((state) =>
    Boolean(state.nodeLookup.get(sourceId)?.dragging),
  );
  const targetMoving = useStore((state) =>
    Boolean(state.nodeLookup.get(targetId)?.dragging),
  );
  const moving = sourceMoving || targetMoving;
  const activeBook = moving ? targets?.movingBook : targets?.book;
  const subscribe = React.useCallback(
    (listener: () => void) => activeBook?.subscribe(id, listener) ?? (() => {}),
    [activeBook, id],
  );
  const routed = React.useSyncExternalStore(
    activeBook ? subscribe : NO_BOOK_SUBSCRIPTION,
    () => activeBook?.get(id),
    () => undefined,
  );
  if (!targets) return null;

  const { corners, material, well } = targets.look;
  const liquid = material === "liquid";
  const flat = well === "flat";
  const sourceLens = lensMaskId(id, "source");
  const targetLens = lensMaskId(id, "target");
  const source = ringCentre(sourceX, sourceY, sourcePosition);
  const target = ringCentre(targetX, targetY, targetPosition);
  const sourceSequence = isSequenceHandle(sourceHandleId);
  const targetSequence = isSequenceHandle(targetHandleId);
  const depth = moving ? 0 : (routed?.depth ?? 0);
  const layer = targets.pipes[depth] ?? targets.pipes[0];
  const depthGirth = DEPTH_GIRTH[depth] ?? 1;
  const depthShadow =
    depth === 0 ? "surface" : depth === 1 ? "middle" : undefined;
  const path =
    routed?.path ??
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
            <PipeBody
              path={path}
              color={color}
              corners={corners}
              shadow="surface"
            />,
            targets.movingUnder,
          )
        : null}
      {moving && flat && targets.movingOver
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
              <PipeBody
                path={path}
                color={color}
                corners={corners}
                girth={depthGirth}
                shadow={depthShadow}
              />
            </g>,
            layer,
          )
        : null}
      {settled && (flat || wipe > 0) && targets.sharp
        ? createPortal(
            wipe > 0 ? (
              <PipeBody
                path={path}
                color={color}
                corners={corners}
                shadow="surface"
                cylindrical={!flat}
              />
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
      {settled && (flat || wipe > 0) && targets.wells
        ? createPortal(
            <>
              {flat ? (
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
                </>
              ) : null}
              {wipe > 0 ? (
                <>
                  <path
                    d={path}
                    fill="none"
                    stroke="currentColor"
                    strokeOpacity={wipe * 0.35}
                    strokeWidth={PIPE_WIDTH + 18}
                    strokeLinejoin="round"
                    strokeLinecap="round"
                  />
                  <path
                    d={path}
                    fill="none"
                    stroke="currentColor"
                    strokeOpacity={wipe}
                    strokeWidth={PIPE_WIDTH + 9}
                    strokeLinejoin="round"
                    strokeLinecap="round"
                  />
                </>
              ) : null}
            </>,
            targets.wells,
          )
        : null}
      {flat && liquid && targets.lensMasks
        ? createPortal(
            <>
              <LensMask id={sourceLens} centre={source} />
              <LensMask id={targetLens} centre={target} />
            </>,
            targets.lensMasks,
          )
        : null}
      {flat && liquid && targets.lenses
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
      {flat && targets.rims
        ? createPortal(
            <>
              <WellRim centre={source} material={material} />
              <WellRim centre={target} material={material} />
            </>,
            targets.rims,
          )
        : null}
      {!flat && (
        <>
          <PortWell
            edgeId={id}
            nodeId={sourceId}
            end="source"
            handleId={sourceHandleId}
            moving={sourceMoving}
            targets={targets}
            centre={source}
            position={sourcePosition}
            color={color}
            material={material}
            sequence={sourceSequence}
          />
          <PortWell
            edgeId={id}
            nodeId={targetId}
            end="target"
            handleId={targetHandleId}
            moving={targetMoving}
            targets={targets}
            centre={target}
            position={targetPosition}
            color={color}
            material={material}
            sequence={targetSequence}
          />
        </>
      )}
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
  fromHandle,
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
  const color = fromHandle?.id ? pipeColor(fromHandle.id) : tokens.colorAccent;
  return (
    <g>
      <path
        d={path}
        fill="none"
        strokeWidth={PIPE_WIDTH}
        strokeOpacity={0.18}
        strokeLinejoin="round"
        style={{ stroke: color }}
      />
      <path
        d={path}
        fill="none"
        strokeWidth={2.2}
        strokeDasharray="6 5"
        strokeLinecap="round"
        style={{ stroke: color }}
      />
      <circle
        cx={toX}
        cy={toY}
        r={4}
        fill="none"
        strokeWidth={1.8}
        style={{ stroke: color }}
      />
    </g>
  );
}
