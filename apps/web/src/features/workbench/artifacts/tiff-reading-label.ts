export type PixelPolygon = readonly (readonly [number, number])[];

export const svgNamespace = "http://www.w3.org/2000/svg";

type ReadingEdge = {
  /** The corner this edge is walked from, once it has been pointed rightwards. */
  x: number;
  y: number;
  run: number;
  rise: number;
  span: number;
};

type ReadingFrame = {
  x: number;
  y: number;
  degrees: number;
  depth: number;
};

function rightwardEdge(
  from: readonly [number, number],
  to: readonly [number, number],
): ReadingEdge {
  const [fromX, fromY] = from;
  const [toX, toY] = to;
  if (toX < fromX || (toX === fromX && toY < fromY)) {
    // Words read left to right whichever corner the detector started from, so an
    // edge that runs back across the page is walked the other way round.
    return {
      x: toX,
      y: toY,
      run: fromX - toX,
      rise: fromY - toY,
      span: Math.hypot(fromX - toX, fromY - toY),
    };
  }
  return {
    x: fromX,
    y: fromY,
    run: toX - fromX,
    rise: toY - fromY,
    span: Math.hypot(toX - fromX, toY - fromY),
  };
}

/**
 * The line a reading is written along, in page pixels.
 *
 * A scan is rarely square to the text it carries, and the detector returns each
 * region as the quadrangle it found, tilted with the writing. So a baseline
 * cannot be assumed: it is one of the region's long edges, pointed left to right
 * because words read that way whichever corner the detector started at, and the
 * higher of them because the reading is written above what it labels. Depth is
 * measured across that edge rather than down the page, so a region turned 45°
 * does not borrow its own diagonal as a cap height.
 */
function readingFrame(points: PixelPolygon): ReadingFrame | null {
  const edges: ReadingEdge[] = [];
  let first: readonly [number, number] | undefined;
  let previous: readonly [number, number] | undefined;
  for (const corner of points) {
    first ??= corner;
    if (previous) edges.push(rightwardEdge(previous, corner));
    previous = corner;
  }
  if (first && previous && first !== previous) {
    edges.push(rightwardEdge(previous, first));
  }
  let longest: ReadingEdge | null = null;
  for (const edge of edges) {
    if (!longest || edge.span > longest.span) longest = edge;
  }
  if (!longest) return null;
  let baseline: ReadingEdge = longest;
  for (const edge of edges) {
    // The edge under the writing is as long as the edge over it and belongs to
    // the line below, so the highest edge of the region is the one to write on.
    if (edge.span < longest.span * 0.9) continue;
    if (edge.y < baseline.y) baseline = edge;
  }
  const length = baseline.span || 1;
  const along = baseline.run / length;
  const across = baseline.rise / length;
  let depth = 0;
  for (const [x, y] of points) {
    // Positive this way is the side the region's body lies on, that is, below
    // the writing when it runs left to right.
    const down = (x - baseline.x) * -across + (y - baseline.y) * along;
    if (down > depth) depth = down;
  }
  return {
    x: baseline.x,
    y: baseline.y,
    degrees: (Math.atan2(baseline.rise, baseline.run) * 180) / Math.PI,
    depth,
  };
}

export function readingLabel(
  points: PixelPolygon,
  reading: string | null | undefined,
): SVGTextElement | null {
  const text = reading?.trim();
  if (!text) return null;
  const frame = readingFrame(points);
  if (!frame) return null;
  const { x, y, degrees, depth } = frame;
  const label = document.createElementNS(svgNamespace, "text");
  label.textContent = text;
  label.setAttribute("x", String(x));
  label.setAttribute("y", String(y));
  label.setAttribute("fill", "darkorange");
  // Half the region's depth, so a page full of readings stays legible as notes
  // on the spans instead of competing with the scan itself. The floor is what a
  // label has to be in page pixels to survive being drawn at all.
  label.setAttribute("font-size", String(Math.max(4, depth * 0.4)));
  label.setAttribute("dominant-baseline", "auto");
  if (degrees) {
    // Turned about the corner it starts from, so the first letter stays on the
    // span and the rest of the word follows the tilt away from it.
    label.setAttribute(
      "transform",
      `rotate(${Number(degrees.toFixed(2))} ${x} ${y})`,
    );
  }
  label.style.pointerEvents = "none";
  return label;
}
