import { tokens } from "@/lib/stylex/tokens.stylex";
import { artifactTypeColor } from "@/features/workbench/canvas/nodes.css";
import type { Point } from "./pipe-routing";

export const RING_RADIUS = 5;
const OUTER_RADIUS = 8.2;
const RING_STROKE = 1.5;
const OUTER_STROKE = 1.35;

export interface FittingProps {
  centre: Point;
  color: string;
  sequence: boolean;
}

export function ConnectorFitting({ centre, color, sequence }: FittingProps) {
  return (
    <g style={{ stroke: color }} fill="none">
      {sequence && (
        <circle
          cx={centre.x}
          cy={centre.y}
          r={OUTER_RADIUS}
          strokeWidth={OUTER_STROKE}
        />
      )}
      <circle
        cx={centre.x}
        cy={centre.y}
        r={RING_RADIUS - RING_STROKE / 2}
        strokeWidth={RING_STROKE}
        style={{ fill: tokens.colorSurface }}
      />
    </g>
  );
}

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

/** Match the well fitting to the product handle without moving its hit area. */
export function connectorCss(scope: string): string {
  const handle = `${scope} .react-flow__handle`;
  const ring = "> span:nth-of-type(3)";
  return `
${handle} ${ring} {
  border: ${RING_STROKE}px solid var(--port) !important;
  border-radius: 50% !important;
  background: ${tokens.colorSurface} !important;
  box-shadow: none !important;
}
${handle}[data-handleid*="::many::"] ${ring}::after {
  content: "";
  position: absolute;
  inset: -${OUTER_RADIUS - RING_RADIUS + OUTER_STROKE / 2 + RING_STROKE}px;
  border: ${OUTER_STROKE}px solid var(--port);
  border-radius: 50%;
  pointer-events: none;
}
${handle}[data-port-hot="true"] ${ring} {
  background: color-mix(in oklab, var(--port) 24%, ${tokens.colorSurface}) !important;
}
`;
}
