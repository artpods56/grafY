import { pipePath, type Point } from "./pipe-routing";

/** Centre-to-centre pitch leaves both strands inside a 10-unit lane. */
const STRAND_OFFSET = 2.65;

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
