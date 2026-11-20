import type { Point } from "./pipe-routing";

/**
 * Where a pipe design places its fittings along a route. A route is the
 * router's corner points, ports first and last; every segment is horizontal
 * or vertical.
 */

/** A straight stretch of a route between two fittings, with its direction. */
export interface Run {
  from: Point;
  to: Point;
  /** Unit direction from `from` to `to`. */
  dx: number;
  dy: number;
  length: number;
}

/** A bend of a route: where its curve starts and ends, and its directions. */
export interface Bend {
  corner: Point;
  /** Unit direction coming into the corner and going out of it. */
  inward: { dx: number; dy: number };
  outward: { dx: number; dy: number };
  /** How far from the corner the curve starts, on both legs. */
  reach: number;
}

function direction(from: Point, to: Point): { dx: number; dy: number } {
  const length = Math.hypot(to.x - from.x, to.y - from.y);
  if (length === 0) return { dx: 0, dy: 0 };
  return { dx: (to.x - from.x) / length, dy: (to.y - from.y) / length };
}

/**
 * Every bend of a route, with the reach `pipePath` gives its curve: the corner
 * radius, cut down to half of the shorter leg.
 */
export function routeBends(points: readonly Point[], radius: number): Bend[] {
  const bends: Bend[] = [];
  for (let index = 1; index < points.length - 1; index += 1) {
    const before = points[index - 1];
    const corner = points[index];
    const after = points[index + 1];
    if (!before || !corner || !after) continue;
    const inLength = Math.hypot(corner.x - before.x, corner.y - before.y);
    const outLength = Math.hypot(after.x - corner.x, after.y - corner.y);
    if (inLength === 0 || outLength === 0) continue;
    const inward = direction(before, corner);
    const outward = direction(corner, after);
    // A straight-through point is no bend.
    if (inward.dx === outward.dx && inward.dy === outward.dy) continue;
    bends.push({
      corner,
      inward,
      outward,
      reach: Math.min(radius, inLength / 2, outLength / 2),
    });
  }
  return bends;
}

/**
 * The straight stretches of a route, each segment trimmed by `endClear` at a
 * port and by `cornerClear` at a bend. Stretches shorter than nothing are
 * dropped.
 */
export function straightRuns(
  points: readonly Point[],
  { endClear, cornerClear }: { endClear: number; cornerClear: number },
): Run[] {
  const runs: Run[] = [];
  const last = points.length - 2;
  for (let index = 0; index <= last; index += 1) {
    const start = points[index];
    const end = points[index + 1];
    if (!start || !end) continue;
    const length = Math.hypot(end.x - start.x, end.y - start.y);
    if (length === 0) continue;
    const { dx, dy } = direction(start, end);
    const head = index === 0 ? endClear : cornerClear;
    const tail = index === last ? endClear : cornerClear;
    const kept = length - head - tail;
    if (kept <= 0) continue;
    runs.push({
      from: { x: start.x + dx * head, y: start.y + dy * head },
      to: { x: end.x - dx * tail, y: end.y - dy * tail },
      dx,
      dy,
      length: kept,
    });
  }
  return runs;
}

/**
 * Offsets along a run of `length` for fittings at least `pitch` apart, spread
 * evenly with half a gap at each end, so lanes of equal length line up.
 */
export function evenStations(length: number, pitch: number): number[] {
  const count = Math.floor(length / pitch);
  if (count < 1) return [];
  const gap = length / count;
  return Array.from({ length: count }, (_, index) => gap * (index + 0.5));
}

/** The point `offset` along a run. */
export function pointOnRun(run: Run, offset: number): Point {
  return { x: run.from.x + run.dx * offset, y: run.from.y + run.dy * offset };
}

/**
 * A path of short straight dashes, one per station, each `length` long and
 * centred on its station along the run's direction. Stroked wide with butt
 * caps, every dash draws one band across the pipe.
 */
export function bandsPath(
  stations: readonly { at: Point; dx: number; dy: number }[],
  length: number,
): string {
  const half = length / 2;
  return stations
    .map(
      ({ at, dx, dy }) =>
        `M${fixed(at.x - dx * half)},${fixed(at.y - dy * half)} L${fixed(at.x + dx * half)},${fixed(at.y + dy * half)}`,
    )
    .join(" ");
}

/**
 * Chevrons pointing along each station's direction, `size` long and as wide,
 * as one open path.
 */
export function chevronsPath(
  stations: readonly { at: Point; dx: number; dy: number }[],
  size: number,
): string {
  const half = size / 2;
  return stations
    .map(({ at, dx, dy }) => {
      // Perpendicular to the direction of flow.
      const px = -dy;
      const py = dx;
      const tip = { x: at.x + dx * half, y: at.y + dy * half };
      const back = { x: at.x - dx * half, y: at.y - dy * half };
      return `M${fixed(back.x + px * half)},${fixed(back.y + py * half)} L${fixed(tip.x)},${fixed(tip.y)} L${fixed(back.x - px * half)},${fixed(back.y - py * half)}`;
    })
    .join(" ");
}

/**
 * The unit normal of a direction that faces the light, which comes from the
 * top left: up for a horizontal run, left for a vertical one, and the upper
 * side of a diagonal.
 */
export function towardLight(dx: number, dy: number): { x: number; y: number } {
  // `0 - v` rather than `-v`, so a zero stays 0 and not -0.
  const x = 0 - dy;
  const y = dx + 0;
  return x + y <= 0 ? { x, y } : { x: 0 - x, y: 0 - y };
}

/**
 * The straight runs of a route, each moved `offset` toward the light and cut
 * short where a bend's curve begins, as one open path: a highlight that
 * stays on the lit side of a pipe at any angle.
 */
export function litEdgePath(
  points: readonly Point[],
  radius: number,
  offset: number,
): string {
  const parts: string[] = [];
  for (let index = 0; index < points.length - 1; index += 1) {
    const start = points[index];
    const end = points[index + 1];
    if (!start || !end) continue;
    const length = Math.hypot(end.x - start.x, end.y - start.y);
    if (length === 0) continue;
    const dx = (end.x - start.x) / length;
    const dy = (end.y - start.y) / length;
    const head = index === 0 ? 0 : Math.min(radius, length / 2);
    const tail = index === points.length - 2 ? 0 : Math.min(radius, length / 2);
    if (length - head - tail <= 0) continue;
    const normal = towardLight(dx, dy);
    const shift = { x: normal.x * offset, y: normal.y * offset };
    parts.push(
      `M${fixed(start.x + dx * head + shift.x)},${fixed(start.y + dy * head + shift.y)} L${fixed(end.x - dx * tail + shift.x)},${fixed(end.y - dy * tail + shift.y)}`,
    );
  }
  return parts.join(" ");
}

/**
 * An SVG path through the points with every bend cut at 45 degrees, `chamfer`
 * back from its corner (less on a short leg), as a circuit trace is drawn.
 */
export function chamferPath(points: readonly Point[], chamfer: number): string {
  const first = points[0];
  if (!first) return "";
  const parts = [`M${fixed(first.x)},${fixed(first.y)}`];
  for (const bend of routeBends(points, chamfer)) {
    const { corner, inward, outward, reach } = bend;
    parts.push(
      `L${fixed(corner.x - inward.dx * reach)},${fixed(corner.y - inward.dy * reach)}`,
      `L${fixed(corner.x + outward.dx * reach)},${fixed(corner.y + outward.dy * reach)}`,
    );
  }
  const last = points[points.length - 1];
  if (last && points.length > 1)
    parts.push(`L${fixed(last.x)},${fixed(last.y)}`);
  return parts.join(" ");
}

function fixed(value: number): string {
  return String(Math.round(value * 100) / 100);
}
