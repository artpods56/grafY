import type { WorldPoint } from "./cell-model";

export type Point = WorldPoint;

/** A corner radius, or one per corner by the corner's point index. */
export type CornerRadius = number | ((index: number) => number);

/** Centre-to-centre pitch leaves both strands inside a 10-unit lane. */
const STRAND_OFFSET = 2.65;

/**
 * SVG path through the points, with square or rounded bends. Segments may run
 * at any angle: a bend between a straight and a diagonal stretch rounds the
 * same way as a right angle.
 */
export function pipePath(
  points: readonly Point[],
  radius: CornerRadius,
): string {
  const first = points[0];
  if (!first) return "";
  const parts = [`M${first.x},${first.y}`];
  for (let index = 1; index < points.length - 1; index += 1) {
    const before = points[index - 1];
    const corner = points[index];
    const after = points[index + 1];
    if (!before || !corner || !after) continue;
    const inLength = Math.hypot(corner.x - before.x, corner.y - before.y);
    const outLength = Math.hypot(after.x - corner.x, after.y - corner.y);
    const cornerRadius = typeof radius === "number" ? radius : radius(index);
    const bend = Math.min(cornerRadius, inLength / 2, outLength / 2);
    if (bend < 0.5) {
      parts.push(`L${corner.x},${corner.y}`);
      continue;
    }
    const enter = {
      x: corner.x - ((corner.x - before.x) / inLength) * bend,
      y: corner.y - ((corner.y - before.y) / inLength) * bend,
    };
    const leave = {
      x: corner.x + ((after.x - corner.x) / outLength) * bend,
      y: corner.y + ((after.y - corner.y) / outLength) * bend,
    };
    parts.push(
      `L${enter.x},${enter.y}`,
      `Q${corner.x},${corner.y} ${leave.x},${leave.y}`,
    );
  }
  const last = points[points.length - 1];
  if (last && points.length > 1) parts.push(`L${last.x},${last.y}`);
  return parts.join(" ");
}

function normal(from: Point, to: Point): Point {
  const x = to.x - from.x;
  const y = to.y - from.y;
  const length = Math.hypot(x, y) || 1;
  return { x: -y / length, y: x / length };
}

/** Offset each run perpendicular to its direction and join their intersections. */
export function twinPaths(points: readonly Point[], radius: number) {
  const runs = points.filter((point, index) => {
    const previous = points[index - 1];
    return !previous || point.x !== previous.x || point.y !== previous.y;
  });
  const offsets = runs.map((point, index) => {
    const previous = runs[index - 1];
    const next = runs[index + 1];
    if (!previous) return next ? normal(point, next) : { x: 0, y: 0 };
    const incoming = normal(previous, point);
    if (!next) return incoming;
    const outgoing = normal(point, next);
    const dot = incoming.x * outgoing.x + incoming.y * outgoing.y;
    // Bound the miter at reversals and during router transitions.
    const scale = 1 / Math.max(0.5, 1 + dot);
    return {
      x: (incoming.x + outgoing.x) * scale,
      y: (incoming.y + outgoing.y) * scale,
    };
  });
  // Which way each corner turns: positive toward the normal side.
  const turns = runs.map((point, index) => {
    const previous = runs[index - 1];
    const next = runs[index + 1];
    if (!previous || !next) return 0;
    const cross =
      (point.x - previous.x) * (next.y - point.y) -
      (point.y - previous.y) * (next.x - point.x);
    return Math.sign(cross);
  });
  function strand(offset: number) {
    return pipePath(
      runs.map((point, index) => ({
        x: point.x + (offsets[index]?.x ?? 0) * offset,
        y: point.y + (offsets[index]?.y ?? 0) * offset,
      })),
      // Concentric with the centre line: the inner strand turns tighter and
      // the outer one wider, so the gap stays even through the bend.
      (index) => Math.max(0, radius - (turns[index] ?? 0) * offset),
    );
  }
  return {
    path: strand(STRAND_OFFSET),
    twin: strand(-STRAND_OFFSET),
    // The line between the strands, for a design that sheathes both.
    centre: pipePath(runs, radius),
  };
}
