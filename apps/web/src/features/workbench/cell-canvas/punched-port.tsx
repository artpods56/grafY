"use client";

import * as React from "react";

import {
  RECESSED_MENISCUS_REACH,
  RECESSED_OUTER_RADIUS,
  RecessedWell,
  WellGradients,
  type CellGlassMaterial,
} from "./cell-glass-stage";
import { PUNCHED_PORT_INSET } from "./cell-model";
import { pipeDesign, type PipeFamily } from "./pipe-visuals";

/**
 * A punched port: the glass stage's recessed well, bored through the card's
 * plate instead of the frost. It is the same drawing as a gutter port's well
 * (`RecessedWell`): the pipe bed at the bottom of the bore, the cavity shade,
 * the bore wall above the stub, and, on liquid glass, the meniscus, caustic and
 * speculars that make it read as cut glass. A connected pipe runs in from the
 * card's outer edge to the port's ring; an open hole shows the bed and ring.
 *
 * Drawn in the card's own units, centred on the port, inside its hit target.
 * Each socket carries its own copy of the well paints under an id of its own,
 * so a card draws correctly with or without a stage on the page.
 */

/** The well's outer lip in the plate. */
export const PUNCH_OUTER_RADIUS = RECESSED_OUTER_RADIUS;
/**
 * Where a port's label may start, from the plate's content edge: clear of
 * the well's lip (and a liquid well's meniscus) with a 3px gap. The lip ends at
 * `PUNCHED_PORT_INSET + PUNCH_OUTER_RADIUS` from the card's outer edge, which
 * is 4px plate inset and 1px border further out than the content edge.
 */
export const PUNCHED_LABEL_INSET = Math.ceil(
  PUNCHED_PORT_INSET + PUNCH_OUTER_RADIUS + RECESSED_MENISCUS_REACH - 5 + 3,
);

/** The drawing box, in flow units: the meniscus fits inside it. */
const BOX = 30;

export interface PunchedPortSocketProps {
  /** The card edge the port faces: inputs left, outputs right. */
  side: "left" | "right";
  color: string;
  sequence: boolean;
  /** A pipe runs into the hole: it is drawn in from the card's edge. */
  connected: boolean;
  /**
   * A connection being dragged is over the port: the hole glows and the pipe
   * shows in it, faint.
   */
  hot: boolean;
  /** The pointer is over the port: the hole glows, and no pipe shows. */
  hovered?: boolean;
  material?: CellGlassMaterial;
  pipe?: PipeFamily;
  /**
   * The card cuts a real hole here (an artifact's preview): the well is bored
   * clean through, with no floor, and the canvas shows through it.
   */
  open?: boolean;
}

export function PunchedPortSocket({
  side,
  color,
  sequence,
  connected,
  hot,
  hovered = false,
  material = "frost",
  pipe = "glass",
  open = false,
}: PunchedPortSocketProps) {
  const prefix = `punch-${React.useId().replace(/[^\w-]/g, "_")}-`;
  const stubOpacity = connected ? 1 : hot ? 0.6 : 0;
  const boreId = `${prefix}bore`;
  return (
    <svg
      aria-hidden="true"
      data-punched-socket={connected ? "connected" : "open"}
      data-punched-bore={open ? "through" : "floored"}
      data-port-ring={sequence ? "list" : "single"}
      width={BOX}
      height={BOX}
      viewBox={`${-BOX / 2} ${-BOX / 2} ${BOX} ${BOX}`}
      style={{ display: "block", overflow: "visible", pointerEvents: "none" }}
    >
      <defs>
        <WellGradients prefix={prefix} />
        {/* The stub ends at the well's lip: past it the pipe is under the
            plate, out of sight. */}
        <clipPath id={boreId}>
          <circle r={PUNCH_OUTER_RADIUS} />
        </clipPath>
      </defs>
      <g data-punched-floor="true">
        <RecessedWell
          well={{
            key: "punched",
            centre: { x: 0, y: 0 },
            exit: side,
            pipeColor: color,
            portColor: color,
            portSequence: sequence,
            pipeTwin: sequence,
          }}
          liquid={material === "liquid"}
          design={pipeDesign(pipe, "opus")}
          prefix={prefix}
          withFloor={!open}
          open={open}
          stubOpacity={stubOpacity}
          stubClipId={boreId}
          glow={hot || hovered}
        />
      </g>
    </svg>
  );
}
