import {
  PIPE_LANE_MIN,
  PIPE_STUB,
  PIPE_STUB_MIN,
  outward,
  type PipeRequest,
  type PipeRoutingBackend,
  type Point,
  type SceneRouter,
} from "../pipe-routing";
import { routeElbows } from "./elbow";

const CUT_MAX = 56;
const CUT_MIN = 5;
const STUB_CUT_SIZES = [CUT_MAX, 36, 26, 10];
const EPSILON = 1e-6;
// x ± y is an unnormalized projection onto a diagonal or its normal.
const OFFSET_CLEARANCE = PIPE_LANE_MIN * Math.SQRT2;

interface Cut {
  id: string;
  index: number;
  corner: Point;
  inX: number;
  inY: number;
  outX: number;
  outY: number;
  length: number;
  offset: number;
  low: number;
  high: number;
}

function resize(cut: Cut, length: number): void {
  const { corner, inX, inY, outX, outY } = cut;
  const slope = (inX + outX) * (inY + outY);
  cut.length = length >= CUT_MIN ? length : 0;
  cut.offset = corner.y - slope * corner.x + length * (slope * inX - inY);
  const start = corner.x - length * inX;
  const end = corner.x + length * outX;
  cut.low = Math.min(start, end);
  cut.high = Math.max(start, end);
}

// Small lane shifts should not stretch a port chamfer by the same amount
// that they move the bend. Use a fixed size within each band of stub room.
function stubCut(length: number): number {
  const room = length - PIPE_STUB_MIN;
  for (const size of STUB_CUT_SIZES) {
    if (size <= room + EPSILON) return size;
  }
  return 0;
}

function findCuts(id: string, points: Point[]): Cut[] {
  const cuts: Cut[] = [];
  for (let index = 1; index < points.length - 1; index += 1) {
    const before = points[index - 1];
    const corner = points[index];
    const after = points[index + 1];
    if (!before || !corner || !after) continue;
    const dx = corner.x - before.x;
    const dy = corner.y - before.y;
    const nextX = after.x - corner.x;
    const nextY = after.y - corner.y;
    if (!((dx && !dy && !nextX && nextY) || (!dx && dy && nextX && !nextY)))
      continue;
    const incoming = Math.abs(dx || dy);
    const outgoing = Math.abs(nextX || nextY);
    const length = Math.min(
      CUT_MAX,
      index === 1 ? stubCut(incoming) : incoming / 2,
      index === points.length - 2 ? stubCut(outgoing) : outgoing / 2,
    );
    if (length < CUT_MIN) continue;
    const cut: Cut = {
      id,
      index,
      corner,
      inX: Math.sign(dx),
      inY: Math.sign(dy),
      outX: Math.sign(nextX),
      outY: Math.sign(nextY),
      length,
      offset: 0,
      low: 0,
      high: 0,
    };
    // A shared leg can disappear completely, but must never leave a sliver.
    const prev = cuts.at(-1);
    const remainder =
      incoming - length - (prev?.index === index - 1 ? prev.length : 0);
    resize(cut, remainder > EPSILON && remainder <= 0.5 ? length - 1 : length);
    if (cut.length) cuts.push(cut);
  }
  return cuts;
}

function compareCuts(a: Cut, b: Cut): number {
  return (
    a.offset - b.offset ||
    a.low - b.low ||
    a.high - b.high ||
    (a.id < b.id ? -1 : a.id > b.id ? 1 : a.index - b.index)
  );
}

function separateDiagonals(cuts: Cut[]): void {
  for (let pass = 0; pass < 2; pass += 1) {
    cuts.sort(compareCuts);
    const conflicts = new Set<Cut>();
    for (const [index, first] of cuts.entries()) {
      if (!first.length || conflicts.has(first)) continue;
      for (let next = index + 1; next < cuts.length; next += 1) {
        const second = cuts[next];
        if (
          !second ||
          second.offset - first.offset >= OFFSET_CLEARANCE - EPSILON
        )
          break;
        if (!second.length || first.id === second.id || conflicts.has(second))
          continue;
        if (
          Math.min(first.high, second.high) - Math.max(first.low, second.low) <=
          EPSILON
        )
          continue;
        if (first.length >= second.length) {
          conflicts.add(first);
          break;
        }
        conflicts.add(second);
      }
    }
    if (!conflicts.size) return;
    // Shrinking can shift the line into another conflict. The second sweep
    // removes any remaining conflicts without moving the surviving cuts.
    for (const cut of conflicts) resize(cut, pass === 0 ? cut.length / 3 : 0);
  }
}

function append(points: Point[], end: Point): void {
  const last = points.at(-1);
  if (last) {
    const dx = end.x - last.x;
    const dy = end.y - last.y;
    if (Math.abs(dx) + Math.abs(dy) <= EPSILON) return;
    const before = points.at(-2);
    if (before) {
      const inX = last.x - before.x;
      const inY = last.y - before.y;
      if (Math.abs(dx * inY - dy * inX) <= EPSILON && dx * inX + dy * inY > 0) {
        points.pop();
      }
    }
  }
  points.push(end);
}

function hasStub(port: Point, next: Point, direction: Point): boolean {
  const dx = next.x - port.x;
  const dy = next.y - port.y;
  return (
    dx * direction.x + dy * direction.y >= PIPE_STUB_MIN - EPSILON &&
    Math.abs(dx * direction.y - dy * direction.x) <= EPSILON
  );
}

function stubEnd(port: Point, direction: Point, avoid: Point): Point {
  const along =
    (avoid.x - port.x) * direction.x + (avoid.y - port.y) * direction.y;
  const length = Math.abs(along - PIPE_STUB) <= 0.5 ? PIPE_STUB * 2 : PIPE_STUB;
  return { x: port.x + direction.x * length, y: port.y + direction.y * length };
}

// Elbow assumes right-to-left ports and can flatten a sub-unit jog. Build
// a detour if the inherited route would break the stub or segment contract.
function withPortStubs(points: Point[], request: PipeRequest): Point[] {
  const { source, target, sourceSide, targetSide } = request;
  const out = outward(sourceSide);
  const into = outward(targetSide);
  const second = points[1];
  const penultimate = points.at(-2);
  if (
    second &&
    penultimate &&
    hasStub(source, second, out) &&
    hasStub(target, penultimate, into) &&
    points.every((point, index) => {
      const prev = points[index - 1];
      if (!prev) return true;
      const dx = Math.abs(point.x - prev.x);
      const dy = Math.abs(point.y - prev.y);
      return (dx <= EPSILON || dy <= EPSILON) && dx + dy > 0.5;
    })
  ) {
    return points;
  }

  const parallel = out.x === 0 ? into.x === 0 : into.y === 0;
  const start = stubEnd(source, out, target);
  const end = stubEnd(target, into, parallel ? start : source);
  if (!parallel) {
    const bend = out.x ? { x: start.x, y: end.y } : { x: end.x, y: start.y };
    return [source, start, bend, end, target];
  }

  if (out.x) {
    const y = Math.max(start.y, end.y) + PIPE_STUB * 2;
    return [source, start, { x: start.x, y }, { x: end.x, y }, end, target];
  }
  const x = Math.max(start.x, end.x) + PIPE_STUB * 2;
  return [source, start, { x, y: start.y }, { x, y: end.y }, end, target];
}

const routeOctilinear: SceneRouter = (scene, options) => {
  const layout = routeElbows(scene, options);
  const groups: Cut[][] = [];
  const cutsByPipe = new Map<string, Cut[]>();
  for (const request of scene.pipes) {
    const { id } = request;
    const routed = layout.get(id);
    if (!routed) continue;
    const { depth } = routed;
    const points = withPortStubs(routed.points, request);
    if (points !== routed.points) layout.set(id, { ...routed, points });
    const cuts = findCuts(id, points);
    if (!cuts.length) continue;
    cutsByPipe.set(id, cuts);
    for (const cut of cuts) {
      const slope = (cut.inX + cut.outX) * (cut.inY + cut.outY);
      const key = depth * 2 + (slope > 0 ? 1 : 0);
      (groups[key] ??= []).push(cut);
    }
  }
  for (const group of groups) {
    if (group) separateDiagonals(group);
  }

  for (const [id, cuts] of cutsByPipe) {
    const routed = layout.get(id);
    if (!routed) continue;
    const points: Point[] = [];
    let next = 0;
    for (const [index, point] of routed.points.entries()) {
      const cut = cuts[next];
      if (cut?.index !== index) {
        append(points, point);
        continue;
      }
      next += 1;
      if (!cut.length) {
        append(points, point);
        continue;
      }
      const { length, inX, inY, outX, outY } = cut;
      append(points, { x: point.x - length * inX, y: point.y - length * inY });
      append(points, {
        x: point.x + length * outX,
        y: point.y + length * outY,
      });
    }
    layout.set(id, { ...routed, points });
  }
  return layout;
};

export const octilinearRouter = {
  id: "octilinear",
  label: "PCB",
  supports: { lanes: true, depth: true },
  angles: "octilinear",
  create: () => routeOctilinear,
} as const satisfies PipeRoutingBackend;
