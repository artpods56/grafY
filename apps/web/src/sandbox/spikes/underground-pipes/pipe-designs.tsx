"use client";

import * as React from "react";

export type PipeDesign = "glass" | "fibre";

export const PIPE_DESIGNS = [
  { value: "glass", label: "Glass" },
  { value: "fibre", label: "Fibre" },
] satisfies { value: PipeDesign; label: string }[];

export const PIPE_WIDTH = 8;

export const PIPE_DESIGN_CSS = `
@keyframes pipe-flow { to { stroke-dashoffset: -72; } }
.pipe-flow { animation: pipe-flow 2s linear infinite; }
@media (prefers-reduced-motion: reduce) {
  .pipe-flow { animation: none; }
}
`;

export function PipeBody({
  design,
  path,
  twin,
  color,
  girth = 1,
  sharp = false,
  flowing = false,
}: {
  design: PipeDesign;
  path: string;
  twin?: string;
  color: string;
  girth?: number;
  sharp?: boolean;
  flowing?: boolean;
}) {
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
      {(sharp || flowing) && (
        <path
          d={strands}
          strokeWidth={(glass && !twin ? 2.5 : 0.9) * girth}
          style={{ stroke: `color-mix(in oklab, ${color} 58%, white)` }}
        />
      )}
      {flowing && (
        <path
          d={strands}
          className="pipe-flow"
          strokeWidth={1.3 * girth}
          strokeDasharray="4 68"
          style={{ stroke: `color-mix(in oklab, ${color} 26%, white)` }}
        />
      )}
    </g>
  );
}
