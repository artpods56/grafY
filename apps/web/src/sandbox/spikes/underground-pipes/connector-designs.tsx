"use client";

import * as React from "react";

import { tokens } from "@/lib/stylex/tokens.stylex";
import { artifactTypeColor } from "@/features/workbench/canvas/nodes.css";
import type { Point } from "./pipe-routing";
import { WELL_SHADOW_INK } from "./pipe-designs";

/**
 * How a port meets its pipe. A connector has two halves:
 *
 *   - the fitting, drawn in the well where the pipe comes up: only a port
 *     with a pipe has one
 *   - the card's own port mark (the product ring and its stem back to the
 *     card), restyled by scoped CSS; an unconnected port shows only this half
 *
 *   ring  the product's port ring, a contact shadow under it
 *   nut   an anodised hex union nut screwed onto a threaded spigot
 *   jack  a plug on an output and a socket on an input; a sequence port has
 *         three pins or holes instead of one
 *   lamp  an indicator lamp whose light fills the well and glows through the
 *         frost around it; an unconnected port's lens stays dark
 *   pad   a plated pad, as a circuit trace ends; the port is its drill hole
 *
 * Every design keeps the product's cues: the type colour, a second ring (or a
 * second pin) for a sequence port, and the swell of a port under the pointer.
 */
export type ConnectorDesign = "ring" | "nut" | "jack" | "lamp" | "pad";

export const CONNECTOR_DESIGNS: readonly {
  value: ConnectorDesign;
  label: string;
}[] = [
  { value: "ring", label: "Ring" },
  { value: "nut", label: "Nut" },
  { value: "jack", label: "Jack" },
  { value: "lamp", label: "Lamp" },
  { value: "pad", label: "Pad" },
];

const PORT_SHADOW_ID = "pipe-stage-port-shadow";
const FACE_SHEEN_ID = "pipe-stage-face-sheen";
const LAMP_FALLOFF_ID = "pipe-stage-lamp-falloff";

/** Nut: circumradius of the hex, so it clears the bore (11.2) with room. */
const NUT_RADIUS = 9.2;
const NUT_SEQUENCE_RADIUS = 9.9;
/** Light from the top left, as the wells are lit: angle of the light. */
const LIGHT_ANGLE = (225 * Math.PI) / 180;
const NUT_METAL = "light-dark(#aab1ba, #747b85)";
const NUT_EDGE =
  "light-dark(color-mix(in srgb, black 30%, transparent), color-mix(in srgb, black 55%, transparent))";

const JACK_RADIUS = 8.4;
const JACK_RUBBER = "light-dark(#3e434a, #2a2e34)";
const JACK_GRIP = "light-dark(#5e656e, #474c55)";
const JACK_BEZEL = "light-dark(#c5cad1, #6c727b)";
const JACK_RECESS = "light-dark(#26292d, #09090b)";

const LAMP_BEZEL = "light-dark(#8e959e, #4c525a)";
const LAMP_HALO_RADIUS = 27;

const PAD_RADIUS = 8;
const PAD_SEQUENCE_RADIUS = 9.4;
const PAD_GOLD = "light-dark(#c39b3a, #c7a24a)";

export interface FittingProps {
  design: ConnectorDesign;
  centre: Point;
  color: string;
  sequence: boolean;
  end: "source" | "target";
  /** `recessed` sits on a riser in a bore; `flat` over a hole in the frost. */
  well: "recessed" | "flat";
  /** Gradient id prefix of the layer the well is drawn in. */
  prefix: string;
}

function hexPoints(centre: Point, radius: number): Point[] {
  return Array.from({ length: 6 }, (_, index) => ({
    x: centre.x + radius * Math.cos((index * Math.PI) / 3),
    y: centre.y + radius * Math.sin((index * Math.PI) / 3),
  }));
}

function polygon(points: readonly Point[]): string {
  return points.map(({ x, y }) => `${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
}

/**
 * A hex nut from straight above: six chamfer facets lit by their angle to the
 * light, and the machined top face over them.
 */
function Nut({ centre, color, sequence, prefix }: FittingProps) {
  const radius = sequence ? NUT_SEQUENCE_RADIUS : NUT_RADIUS;
  const outer = hexPoints(centre, radius);
  const inner = hexPoints(centre, radius * 0.7);
  const face = radius * 0.8;
  return (
    <g>
      <polygon
        points={polygon(
          hexPoints({ x: centre.x + 0.9, y: centre.y + 2.4 }, radius),
        )}
        style={{ fill: WELL_SHADOW_INK }}
      />
      <polygon
        points={polygon(outer)}
        strokeWidth={0.5}
        style={{
          fill: `color-mix(in srgb, ${color} 42%, ${NUT_METAL})`,
          stroke: NUT_EDGE,
        }}
      />
      {outer.map((corner, index) => {
        const next = outer[(index + 1) % 6] ?? corner;
        const innerNext = inner[(index + 1) % 6] ?? corner;
        const innerCorner = inner[index] ?? corner;
        const normal = ((index * 60 + 30) * Math.PI) / 180;
        const light = Math.cos(normal - LIGHT_ANGLE);
        return (
          <polygon
            key={index}
            points={polygon([corner, next, innerNext, innerCorner])}
            fill={light > 0 ? "white" : "black"}
            fillOpacity={Math.abs(light) * (light > 0 ? 0.5 : 0.42)}
          />
        );
      })}
      <circle
        cx={centre.x}
        cy={centre.y}
        r={face}
        strokeWidth={0.5}
        style={{
          fill: `color-mix(in srgb, ${color} 46%, ${NUT_METAL})`,
          stroke: NUT_EDGE,
        }}
      />
      <circle
        cx={centre.x}
        cy={centre.y}
        r={face}
        fill={`url(#${prefix}${FACE_SHEEN_ID})`}
      />
      {sequence ? (
        <circle
          cx={centre.x}
          cy={centre.y}
          r={face - 1.4}
          fill="none"
          strokeWidth={0.6}
          style={{ stroke: NUT_EDGE }}
        />
      ) : null}
    </g>
  );
}

/** An output's plug in a gripped rubber boot, or an input's socket bezel. */
function Jack({ centre, color, end, prefix }: FittingProps) {
  const plug = end === "source";
  return (
    <g>
      <circle
        cx={centre.x + 0.8}
        cy={centre.y + 2.2}
        r={JACK_RADIUS}
        style={{ fill: WELL_SHADOW_INK }}
      />
      {plug ? (
        <>
          <circle
            cx={centre.x}
            cy={centre.y}
            r={JACK_RADIUS}
            style={{ fill: JACK_RUBBER }}
          />
          {/* Grip ridges round the boot. */}
          <circle
            cx={centre.x}
            cy={centre.y}
            r={JACK_RADIUS - 0.9}
            fill="none"
            strokeWidth={1.3}
            strokeDasharray="1.1 1.24"
            style={{ stroke: JACK_GRIP }}
          />
          <circle
            cx={centre.x}
            cy={centre.y}
            r={JACK_RADIUS - 2.4}
            fill="none"
            strokeWidth={1.1}
            style={{ stroke: color }}
          />
        </>
      ) : (
        <>
          <circle
            cx={centre.x}
            cy={centre.y}
            r={JACK_RADIUS}
            strokeWidth={0.5}
            style={{ fill: JACK_BEZEL, stroke: NUT_EDGE }}
          />
          {/* Two screws hold the socket's plate. */}
          {[-1, 1].map((side) => (
            <circle
              key={side}
              cx={centre.x + side * 5.2}
              cy={centre.y - side * 5.2}
              r={0.85}
              style={{ fill: NUT_EDGE }}
            />
          ))}
          <circle
            cx={centre.x}
            cy={centre.y}
            r={6.3}
            style={{ fill: JACK_RECESS }}
          />
        </>
      )}
      <circle
        cx={centre.x}
        cy={centre.y}
        r={JACK_RADIUS}
        fill={`url(#${prefix}${FACE_SHEEN_ID})`}
      />
    </g>
  );
}

/** The lamp's housing: its light spilling into the bore, a bezel and a lens. */
function Lamp({ centre, color, well, prefix }: FittingProps) {
  const spill = well === "recessed" ? 11.2 : 12;
  return (
    <g>
      {/* On a light sheet the lit bore is pale, not dark. */}
      <circle
        cx={centre.x}
        cy={centre.y}
        r={spill}
        fillOpacity={0.7}
        style={{
          fill: `light-dark(color-mix(in srgb, ${color} 55%, white), ${color})`,
        }}
      />
      <circle
        cx={centre.x}
        cy={centre.y}
        r={spill}
        fill={`url(#${prefix}${LAMP_FALLOFF_ID})`}
      />
      <circle
        cx={centre.x}
        cy={centre.y}
        r={7.2}
        fill="none"
        strokeWidth={1.7}
        style={{ stroke: LAMP_BEZEL }}
      />
      <circle cx={centre.x} cy={centre.y} r={6.4} style={{ fill: color }} />
      <circle
        cx={centre.x}
        cy={centre.y}
        r={3.4}
        style={{ fill: `color-mix(in srgb, ${color} 30%, white)` }}
      />
    </g>
  );
}

/** A plated pad: flat metal, a lighter rim; a sequence pad has two lands. */
function Pad({ centre, color, sequence, prefix }: FittingProps) {
  const radius = sequence ? PAD_SEQUENCE_RADIUS : PAD_RADIUS;
  const metal = `color-mix(in srgb, ${color} 12%, ${PAD_GOLD})`;
  return (
    <g>
      <circle
        cx={centre.x + 0.6}
        cy={centre.y + 1.8}
        r={radius}
        style={{ fill: WELL_SHADOW_INK }}
      />
      <circle
        cx={centre.x}
        cy={centre.y}
        r={radius}
        strokeWidth={0.7}
        style={{
          fill: metal,
          stroke: `color-mix(in srgb, ${metal} 55%, white)`,
        }}
      />
      <circle
        cx={centre.x}
        cy={centre.y}
        r={radius}
        fill={`url(#${prefix}${FACE_SHEEN_ID})`}
        fillOpacity={0.6}
      />
      {sequence ? (
        <circle
          cx={centre.x}
          cy={centre.y}
          r={radius - 2.4}
          fill="none"
          strokeWidth={0.9}
          style={{ stroke: `color-mix(in srgb, ${metal} 45%, black)` }}
        />
      ) : null}
    </g>
  );
}

/** The fitting in a port's well, between the riser and the glass wall. */
export function ConnectorFitting(props: FittingProps) {
  switch (props.design) {
    case "ring":
      // The product ring floats over the riser; a contact shadow seats it.
      return props.well === "recessed" ? (
        <circle
          cx={props.centre.x}
          cy={props.centre.y + 1.1}
          r={props.sequence ? 9.4 : 6.4}
          fill={`url(#${props.prefix}${PORT_SHADOW_ID})`}
        />
      ) : null;
    case "nut":
      return <Nut {...props} />;
    case "jack":
      return <Jack {...props} />;
    case "lamp":
      return <Lamp {...props} />;
    case "pad":
      return <Pad {...props} />;
  }
}

/**
 * A lit lamp's glow in the frost around its well: frosted glass scatters the
 * light. A gradient of its own colour per lamp; an active (hovered or
 * selected) pipe's lamps brighten and breathe.
 */
export function ConnectorHalo({
  design,
  id,
  centre,
  color,
  active,
}: {
  design: ConnectorDesign;
  id: string;
  centre: Point;
  color: string;
  active: boolean;
}) {
  if (design !== "lamp") return null;
  return (
    <g>
      <radialGradient id={id}>
        <stop offset="0.36" stopOpacity={0.42} style={{ stopColor: color }} />
        <stop offset="0.62" stopOpacity={0.14} style={{ stopColor: color }} />
        <stop offset="1" stopOpacity={0} style={{ stopColor: color }} />
      </radialGradient>
      <circle
        className={active ? "pipe-lamp-breathe" : undefined}
        cx={centre.x}
        cy={centre.y}
        r={LAMP_HALO_RADIUS}
        fill={`url(#${id})`}
        opacity={active ? 1 : 0.72}
      />
    </g>
  );
}

/** Gradients the fittings share, per layer (`prefix`). */
export function ConnectorDefs({ prefix }: { prefix: string }) {
  return (
    <>
      {/* Contact shadow directly beneath the port ring resting on top of
          the rising pipe collar. */}
      <radialGradient id={prefix + PORT_SHADOW_ID}>
        <stop offset="55%" stopColor="black" stopOpacity={0.42} />
        <stop offset="82%" stopColor="black" stopOpacity={0.16} />
        <stop offset="100%" stopColor="black" stopOpacity={0} />
      </radialGradient>
      {/* A machined face under top-left light. */}
      <linearGradient id={prefix + FACE_SHEEN_ID} x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stopColor="white" stopOpacity={0.45} />
        <stop offset="42%" stopColor="white" stopOpacity={0.04} />
        <stop offset="58%" stopColor="black" stopOpacity={0} />
        <stop offset="100%" stopColor="black" stopOpacity={0.28} />
      </linearGradient>
      {/* A lamp lights the middle of its bore most. */}
      <radialGradient id={prefix + LAMP_FALLOFF_ID}>
        <stop offset="40%" stopColor="black" stopOpacity={0} />
        <stop offset="100%" stopColor="black" stopOpacity={0.42} />
      </radialGradient>
    </>
  );
}

/**
 * Each handle's type colour as `--port`, so the port CSS below can mix with
 * it: the product only sets the colour inline, on the ring's border.
 */
export function portColorCss(scope: string, typeIds: Iterable<string>): string {
  const rules = [
    `${scope} .react-flow__handle { --port: ${tokens.colorMuted}; }`,
  ];
  for (const typeId of new Set(typeIds)) {
    rules.push(
      `${scope} .react-flow__handle[data-handleid*="::${typeId}::"] { --port: ${artifactTypeColor(typeId, tokens.colorMuted)}; }`,
    );
  }
  // A generic port still open is drawn in the muted colour.
  rules.push(
    `${scope} [data-port-open="true"] .react-flow__handle { --port: ${tokens.colorMuted}; }`,
  );
  return rules.join("\n");
}

const HOLE = "light-dark(#24272b, #060607)";
const RIM_INK =
  "light-dark(color-mix(in srgb, black 35%, transparent), color-mix(in srgb, black 62%, transparent))";

/** Three small dots, as a sequence port's pins or holes, over `base`. */
function threeDots(dot: string, base: string): string {
  const at = ["50% 27%", "27% 67%", "73% 67%"];
  return [
    ...at.map(
      (position) =>
        `radial-gradient(circle at ${position}, ${dot} 0 0.95px, transparent 1.35px)`,
    ),
    base,
  ].join(", ");
}

/**
 * The card's half of each connector: its port ring (`span:nth-of-type(3)` of
 * the handle) and the stem back to the card (`span:nth-of-type(2)`). The
 * product sets their colours inline, hence `!important`.
 */
export function connectorCss(scope: string): string {
  const handle = ".react-flow__handle";
  const many = `${handle}[data-handleid*="::many::"]`;
  const hot = `${handle}[data-port-hot="true"]`;
  const ring = "> span:nth-of-type(3)";
  const stem = "> span:nth-of-type(2)";
  const on = (design: ConnectorDesign) =>
    `${scope}[data-connector="${design}"]`;
  return `
${on("nut")} ${handle} ${ring} {
  box-shadow: 0 0 0 1px ${RIM_INK} !important;
}
${on("nut")} ${many} ${ring} {
  box-shadow: 0 0 0 1px ${RIM_INK}, 0 0 0 2.5px color-mix(in srgb, var(--port) 55%, white), 0 0 0 3.4px ${RIM_INK} !important;
}
${on("nut")} ${handle} ${stem} {
  height: 4px !important;
  margin-top: -2px !important;
  opacity: 1 !important;
  background:
    repeating-linear-gradient(90deg, color-mix(in srgb, black 30%, transparent) 0 0.8px, transparent 0.8px 1.9px),
    linear-gradient(color-mix(in srgb, var(--port) 30%, white), color-mix(in srgb, var(--port) 40%, #7c838c) 55%, color-mix(in srgb, var(--port) 35%, #2a2d31)) !important;
}

${on("jack")} ${handle}.source ${ring} {
  border: 1.5px solid color-mix(in srgb, var(--port) 55%, white) !important;
  background: radial-gradient(circle at 34% 30%, color-mix(in srgb, var(--port) 20%, white) 0 1px, transparent 2.6px), var(--port) !important;
  box-shadow: 0 0.6px 1.2px color-mix(in srgb, black 55%, transparent) !important;
}
${on("jack")} ${many}.source ${ring} {
  background: ${threeDots("color-mix(in srgb, var(--port) 15%, white)", "var(--port)")} !important;
}
${on("jack")} ${handle}.target ${ring} {
  background: ${HOLE} !important;
  box-shadow: inset 0.8px 1.4px 1.6px black, 0 0 0 0.6px ${RIM_INK} !important;
}
${on("jack")} ${many}.target ${ring} {
  background: ${threeDots(HOLE, "color-mix(in srgb, var(--port) 30%, light-dark(#dfe3e8, #3b4047))")} !important;
  box-shadow: inset 0.6px 1px 1.2px color-mix(in srgb, black 55%, transparent), 0 0 0 0.6px ${RIM_INK} !important;
}
${on("jack")} ${hot} ${ring} {
  filter: brightness(1.15) drop-shadow(0 0 2px var(--port));
}
${on("jack")} ${handle} ${stem} {
  height: 3px !important;
  margin-top: -1.5px !important;
  border-radius: 1.5px;
  opacity: 1 !important;
  background: linear-gradient(color-mix(in srgb, var(--port) 40%, #8b929b), color-mix(in srgb, var(--port) 35%, #2a2e34)) !important;
}

${on("lamp")} ${handle} ${ring} {
  border: 1.5px solid color-mix(in srgb, var(--port) 50%, white) !important;
  background: radial-gradient(circle at 35% 31%, white 0 0.8px, transparent 2.2px), color-mix(in srgb, var(--port) 28%, transparent) !important;
  box-shadow: 0 0 0 1px ${RIM_INK} !important;
}
${on("lamp")} ${many} ${ring} {
  box-shadow: 0 0 0 1px ${RIM_INK}, 0 0 0 2.4px color-mix(in srgb, var(--port) 45%, white), 0 0 0 3.2px ${RIM_INK} !important;
}
${on("lamp")} ${hot} ${ring} {
  background: radial-gradient(circle at 35% 31%, white 0 0.8px, transparent 2.2px), color-mix(in srgb, var(--port) 55%, white) !important;
  box-shadow: 0 0 0 1px ${RIM_INK}, 0 0 8px 2px var(--port) !important;
}
${on("lamp")} ${handle} ${stem} {
  height: 1.5px !important;
  margin-top: -0.75px !important;
  opacity: 0.9 !important;
  background: color-mix(in srgb, var(--port) 60%, white) !important;
  box-shadow: 0 0 3px 0.5px var(--port);
}

${on("pad")} ${handle} ${ring} {
  background: radial-gradient(circle at 62% 68%, color-mix(in srgb, white 14%, transparent), transparent 70%), ${HOLE} !important;
}
${on("pad")} ${many} ${ring} {
  box-shadow: 0 0 0 1.2px ${HOLE}, 0 0 0 2.6px var(--port) !important;
}
${on("pad")} ${hot} ${ring} {
  background: var(--port) !important;
}
${on("pad")} ${handle} ${stem} {
  height: 2.6px !important;
  margin-top: -1.3px !important;
  opacity: 1 !important;
  background: var(--port) !important;
}

@keyframes pipe-lamp-breathe { 50% { opacity: 0.7; } }
.pipe-lamp-breathe { animation: pipe-lamp-breathe 1.8s ease-in-out infinite; }
@media (prefers-reduced-motion: reduce) {
  .pipe-lamp-breathe { animation: none; }
}
`;
}
