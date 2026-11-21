/**
 * Motion for the cell canvas: snapping a dragged card with hysteresis, the
 * small magnetic tug towards the pointer, the card's settle into its cell, and
 * the pipe morph between two routes.
 *
 * Pure geometry and time: no React, DOM or React Flow import, so every helper
 * runs under a plain unit test.
 */

import {
  CELL_PIPE_STUB_MIN,
  CELL_SIZE,
  type CellCoord,
  type CellDir,
  type WorldPoint,
} from "./cell-model";

/**
 * Extra cells past the half-way line before a dragged card changes cell: 6px
 * on the 25px lattice.
 */
export const SNAP_HYSTERESIS_CELLS = 0.24;
/** Share of the pointer's offset from the snapped cell the card follows. */
export const MAGNETIC_TUG_FACTOR = 0.15;
/** Furthest a card leans out of its snapped cell, in flow units. */
export const MAGNETIC_TUG_MAX_PX = 6;
/**
 * Angular frequency of the card's critically damped settle spring, in rad/s.
 * At 20 a one-cell hop from rest covers 95% of the way in about 240ms.
 */
export const SETTLE_OMEGA = 20;
/** Under this distance (flow units) and speed (units/s) the card lands. */
export const SETTLE_REST_DISTANCE = 0.25;
export const SETTLE_REST_SPEED = 2;
/** A settle never runs longer than this, whatever its velocity. */
export const SETTLE_MAX_DURATION_MS = 1000;
/** Time a pipe takes to morph from one route to the next. */
export const MORPH_DURATION_MS = 180;

/**
 * Whether to play the canvas's own motion. Off under reduced motion, and where
 * `matchMedia` is missing (a server render, jsdom), so tests see the end state.
 */
export function shouldAnimateMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    !window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

const EPSILON = 1e-6;
const MAX_MORPH_SAMPLES = 24;

/** `-0` reads as `0`, so snapped cells and offsets compare cleanly. */
function positiveZero(value: number): number {
  return value === 0 ? 0 : value;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function snapAxis(raw: number, current: number): number {
  if (Math.abs(raw - current) <= 0.5 + SNAP_HYSTERESIS_CELLS) {
    return positiveZero(current);
  }
  return positiveZero(Math.round(raw));
}

/**
 * The cell a dragged card's origin snaps to. Each axis keeps its current cell
 * until the pointer is {@link SNAP_HYSTERESIS_CELLS} past the half-way line,
 * so a card resting on a boundary does not chatter; once it leaves, it lands
 * on the pointer's nearest cell however far a fast drag jumped.
 */
export function snapCellWithHysteresis(
  rawWorld: WorldPoint,
  currentCell: CellCoord,
): CellCoord {
  return {
    col: snapAxis(rawWorld.x / CELL_SIZE, currentCell.col),
    row: snapAxis(rawWorld.y / CELL_SIZE, currentCell.row),
  };
}

/** How far the card leans from its snapped cell towards the raw pointer. */
export function magneticTugOffset(
  rawWorld: WorldPoint,
  snappedCell: CellCoord,
): WorldPoint {
  const dx = rawWorld.x - snappedCell.col * CELL_SIZE;
  const dy = rawWorld.y - snappedCell.row * CELL_SIZE;
  return {
    x: positiveZero(
      clamp(
        dx * MAGNETIC_TUG_FACTOR,
        -MAGNETIC_TUG_MAX_PX,
        MAGNETIC_TUG_MAX_PX,
      ),
    ),
    y: positiveZero(
      clamp(
        dy * MAGNETIC_TUG_FACTOR,
        -MAGNETIC_TUG_MAX_PX,
        MAGNETIC_TUG_MAX_PX,
      ),
    ),
  };
}

export function easeOutCubic(t: number): number {
  const clamped = clamp(t, 0, 1);
  return 1 - (1 - clamped) ** 3;
}

export function interpolatePoint(
  a: WorldPoint,
  b: WorldPoint,
  t: number,
): WorldPoint {
  return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t };
}

// --- Anchoring a route to moving ports ------------------------------------

function outward(dir: CellDir): WorldPoint {
  switch (dir) {
    case "left":
      return { x: -1, y: 0 };
    case "right":
      return { x: 1, y: 0 };
    case "top":
      return { x: 0, y: -1 };
    case "bottom":
      return { x: 0, y: 1 };
  }
}

function isHorizontal(dir: CellDir): boolean {
  return dir === "left" || dir === "right";
}

function samePoint(a: WorldPoint | undefined, b: WorldPoint): boolean {
  return a !== undefined && a.x === b.x && a.y === b.y;
}

function along(from: WorldPoint, to: WorldPoint, out: WorldPoint): number {
  return (to.x - from.x) * out.x + (to.y - from.y) * out.y;
}

function across(from: WorldPoint, to: WorldPoint, out: WorldPoint): number {
  return (to.x - from.x) * out.y - (to.y - from.y) * out.x;
}

function isOrthogonalSegment(a: WorldPoint, b: WorldPoint): boolean {
  return Math.abs(a.x - b.x) < EPSILON || Math.abs(a.y - b.y) < EPSILON;
}

function isOrthogonal(points: readonly WorldPoint[]): boolean {
  for (let index = 1; index < points.length; index += 1) {
    const a = points[index - 1];
    const b = points[index];
    if (a && b && !isOrthogonalSegment(a, b)) return false;
  }
  return true;
}

/** Whether the run from `port` to `next` leaves along `out` for a full stub. */
function holdsStub(
  port: WorldPoint,
  next: WorldPoint | undefined,
  out: WorldPoint,
): boolean {
  if (!next) return false;
  return (
    Math.abs(across(port, next, out)) < EPSILON &&
    along(port, next, out) >= CELL_PIPE_STUB_MIN - EPSILON
  );
}

/**
 * Drop repeated points and corners that do not turn. A corner that doubles
 * back stays, so a stub never silently swallows a reversal.
 */
function simplify(points: readonly WorldPoint[]): WorldPoint[] {
  const distinct: WorldPoint[] = [];
  for (const point of points) {
    const last = distinct.at(-1);
    if (
      last &&
      Math.abs(last.x - point.x) < EPSILON &&
      Math.abs(last.y - point.y) < EPSILON
    ) {
      continue;
    }
    distinct.push({ ...point });
  }
  const kept: WorldPoint[] = [];
  for (let index = 0; index < distinct.length; index += 1) {
    const point = distinct[index];
    if (!point) continue;
    const before = kept.at(-1);
    const after = distinct[index + 1];
    if (before && after) {
      const ax = point.x - before.x;
      const ay = point.y - before.y;
      const bx = after.x - point.x;
      const by = after.y - point.y;
      const straight = Math.abs(ax * by - ay * bx) < EPSILON;
      const forward = ax * bx + ay * by > 0;
      if (straight && forward) continue;
    }
    kept.push(point);
  }
  return kept;
}

/**
 * The lowest coordinate on one axis that clears both stubs: each stub needs
 * `(value - port) * out >= CELL_PIPE_STUB_MIN`. `null` when no value does.
 */
function sharedRun(
  source: number,
  sourceOut: number,
  target: number,
  targetOut: number,
): number | null {
  let low = Number.NEGATIVE_INFINITY;
  let high = Number.POSITIVE_INFINITY;
  for (const [port, out] of [
    [source, sourceOut],
    [target, targetOut],
  ] as const) {
    if (out > 0) low = Math.max(low, port + CELL_PIPE_STUB_MIN);
    else high = Math.min(high, port - CELL_PIPE_STUB_MIN);
  }
  if (low > high + EPSILON) return null;
  if (Number.isFinite(low) && Number.isFinite(high)) return (low + high) / 2;
  return Number.isFinite(low) ? low : high;
}

/**
 * A short orthogonal route between two ports with full stubs, used when the
 * old route has nothing worth keeping.
 */
function orthogonalLink(
  source: WorldPoint,
  sourceExit: CellDir,
  target: WorldPoint,
  targetExit: CellDir,
): WorldPoint[] {
  const start = outward(sourceExit);
  const end = outward(targetExit);
  const a = {
    x: source.x + start.x * CELL_PIPE_STUB_MIN,
    y: source.y + start.y * CELL_PIPE_STUB_MIN,
  };
  const b = {
    x: target.x + end.x * CELL_PIPE_STUB_MIN,
    y: target.y + end.y * CELL_PIPE_STUB_MIN,
  };
  const sourceAcross = isHorizontal(sourceExit);
  const targetAcross = isHorizontal(targetExit);

  if (sourceAcross && targetAcross) {
    const x = sharedRun(source.x, start.x, target.x, end.x);
    if (x !== null) {
      return simplify([source, { x, y: source.y }, { x, y: target.y }, target]);
    }
    const y =
      Math.abs(source.y - target.y) < 1
        ? source.y + CELL_SIZE
        : (source.y + target.y) / 2;
    return simplify([source, a, { x: a.x, y }, { x: b.x, y }, b, target]);
  }

  if (!sourceAcross && !targetAcross) {
    const y = sharedRun(source.y, start.y, target.y, end.y);
    if (y !== null) {
      return simplify([source, { x: source.x, y }, { x: target.x, y }, target]);
    }
    const x =
      Math.abs(source.x - target.x) < 1
        ? source.x + CELL_SIZE
        : (source.x + target.x) / 2;
    return simplify([source, a, { x, y: a.y }, { x, y: b.y }, b, target]);
  }

  // One port leaves across, the other up or down: a single corner if both
  // stubs fit, else a jog between the two stub ends.
  const corner = sourceAcross
    ? { x: target.x, y: source.y }
    : { x: source.x, y: target.y };
  if (
    along(source, corner, start) >= CELL_PIPE_STUB_MIN - EPSILON &&
    along(target, corner, end) >= CELL_PIPE_STUB_MIN - EPSILON
  ) {
    return simplify([source, corner, target]);
  }
  const jog = sourceAcross ? { x: a.x, y: b.y } : { x: b.x, y: a.y };
  return simplify([source, a, jog, b, target]);
}

/**
 * Slide the corner at `points[bend]` along the retained stretch towards
 * `points[next]` so it sits on the port's axis. When that leaves the stub
 * short, move the whole stretch out to a full stub instead.
 */
function bendToPort(
  points: WorldPoint[],
  port: WorldPoint,
  exit: CellDir,
  bend: number,
  next: number,
): boolean {
  const corner = points[bend];
  const following = points[next];
  if (!corner || !following) return false;
  const out = outward(exit);
  // The retained stretch must cross the stub's axis to carry the corner.
  if (Math.abs(along(corner, following, out)) > EPSILON) return false;
  if (Math.abs(across(corner, following, out)) < EPSILON) return false;

  const reach = along(port, corner, out);
  const stub = Math.max(reach, CELL_PIPE_STUB_MIN);
  const shift = stub - reach;
  points[bend] = { x: port.x + out.x * stub, y: port.y + out.y * stub };
  points[next] = {
    x: following.x + out.x * shift,
    y: following.y + out.y * shift,
  };
  return true;
}

/**
 * Re-attach a routed pipe's stubs to the ports where they are drawn now,
 * keeping the inner run of the route. The result is always orthogonal: a
 * straight pipe stays straight while its ends line up, a small offset grows
 * a clean jog, and a route whose inner run cannot carry the move falls back
 * to a short orthogonal link with full stubs.
 */
export function anchorPipeEndpoints(
  points: readonly WorldPoint[],
  source: WorldPoint,
  sourceExit: CellDir,
  target: WorldPoint,
  targetExit: CellDir,
): WorldPoint[] {
  if (samePoint(points[0], source) && samePoint(points.at(-1), target)) {
    return points.map((point) => ({ ...point }));
  }

  const start = outward(sourceExit);
  if (points.length <= 3) {
    // A straight pipe stretches along its axis without growing bends.
    if (
      points.length === 2 &&
      Math.abs(across(source, target, start)) < EPSILON &&
      along(source, target, start) > EPSILON
    ) {
      return [{ ...source }, { ...target }];
    }
    return orthogonalLink(source, sourceExit, target, targetExit);
  }

  const moved = points.map((point) => ({ ...point }));
  const last = moved.length - 1;
  moved[0] = { ...source };
  moved[last] = { ...target };
  const anchored =
    bendToPort(moved, source, sourceExit, 1, 2) &&
    bendToPort(moved, target, targetExit, last - 1, last - 2);
  if (anchored) {
    // The far end may have shifted the stretch the near end leaned on.
    moved[0] = { ...source };
    moved[last] = { ...target };
    const result = simplify(moved);
    if (
      isOrthogonal(result) &&
      holdsStub(source, result[1], start) &&
      holdsStub(target, result.at(-2), outward(targetExit))
    ) {
      return result;
    }
  }
  return orthogonalLink(source, sourceExit, target, targetExit);
}

// --- Morphing between two routes -----------------------------------------

function directions(points: readonly WorldPoint[]): string {
  let key = "";
  for (let index = 1; index < points.length; index += 1) {
    const a = points[index - 1];
    const b = points[index];
    if (!a || !b) continue;
    const dx = Math.abs(b.x - a.x) < EPSILON ? 0 : Math.sign(b.x - a.x);
    const dy = Math.abs(b.y - a.y) < EPSILON ? 0 : Math.sign(b.y - a.y);
    key += String(4 + 3 * dx + dy);
  }
  return key;
}

/** Corner distances along the run, normalised to 0..1. */
function knots(points: readonly WorldPoint[]): number[] {
  const distances = [0];
  let length = 0;
  for (let index = 1; index < points.length; index += 1) {
    const a = points[index - 1];
    const b = points[index];
    if (a && b) length += Math.hypot(b.x - a.x, b.y - a.y);
    distances.push(length);
  }
  return length > 0 ? distances.map((distance) => distance / length) : [0, 1];
}

function sample(
  points: readonly WorldPoint[],
  distances: readonly number[],
  at: readonly number[],
): WorldPoint[] {
  let index = 1;
  return at.map((fraction) => {
    while (index < distances.length - 1 && (distances[index] ?? 1) < fraction) {
      index += 1;
    }
    const a = points[index - 1] ?? points[0] ?? { x: 0, y: 0 };
    const b = points[index] ?? a;
    const low = distances[index - 1] ?? 0;
    const high = distances[index] ?? 1;
    return interpolatePoint(
      a,
      b,
      high > low ? (fraction - low) / (high - low) : 0,
    );
  });
}

/** Give a straight pipe its two stub corners, so the stubs stay straight. */
function stubbed(points: readonly WorldPoint[]): readonly WorldPoint[] {
  const [source, target] = points;
  if (points.length !== 2 || !source || !target) return points;
  const length = Math.hypot(target.x - source.x, target.y - source.y);
  if (length <= 0) return points;
  const stub = Math.min(CELL_PIPE_STUB_MIN / length, 0.5);
  return [
    source,
    interpolatePoint(source, target, stub),
    interpolatePoint(target, source, stub),
    target,
  ];
}

function matchPoints(
  from: readonly WorldPoint[],
  to: readonly WorldPoint[],
): readonly [readonly WorldPoint[], readonly WorldPoint[]] {
  if (from.length === to.length && directions(from) === directions(to)) {
    return [from, to];
  }
  const start = stubbed(from);
  const end = stubbed(to);
  const fromPort = start[0];
  const fromEnd = start.at(-1);
  const toPort = end[0];
  const toEnd = end.at(-1);
  if (!fromPort || !fromEnd || !toPort || !toEnd) return [from, to];
  const fromRun = start.slice(1, -1);
  const toRun = end.slice(1, -1);
  if (fromRun.length === 0 || toRun.length === 0) {
    return [
      [fromPort, fromEnd],
      [toPort, toEnd],
    ];
  }
  // Sample both inner runs at every corner of either. The port ends match
  // directly, so the stubs stay attached while the rest of the pipe bends.
  const fromKnots = knots(fromRun);
  const toKnots = knots(toRun);
  const at = [...new Set([...fromKnots, ...toKnots])].sort((a, b) => a - b);
  const samples =
    at.length <= MAX_MORPH_SAMPLES
      ? at
      : Array.from(
          { length: MAX_MORPH_SAMPLES },
          (_, index) => index / (MAX_MORPH_SAMPLES - 1),
        );
  return [
    [fromPort, ...sample(fromRun, fromKnots, samples), fromEnd],
    [toPort, ...sample(toRun, toKnots, samples), toEnd],
  ];
}

/**
 * The pipe part way from one route to another, eased out. The ends travel
 * straight from port to port; the inner runs are matched by arc length.
 */
export function morphPipePoints(
  from: readonly WorldPoint[],
  to: readonly WorldPoint[],
  progress: number,
): WorldPoint[] {
  if (progress <= 0) return from.map((point) => ({ ...point }));
  if (progress >= 1) return to.map((point) => ({ ...point }));
  const [start, end] = matchPoints(from, to);
  const eased = easeOutCubic(progress);
  return start.map((point, index) =>
    interpolatePoint(point, end[index] ?? point, eased),
  );
}

// --- Card settle -----------------------------------------------------------

/**
 * A card gliding into its cell on a critically damped spring. `origin` and
 * `originVelocity` are where and how fast the card was at `startMs`; the
 * spring's closed form gives every later frame exactly, so the glide does not
 * depend on frame rate and a retarget carries the card's momentum.
 */
export interface CardSettleState {
  origin: WorldPoint;
  originVelocity: WorldPoint;
  to: WorldPoint;
  current: WorldPoint;
  /** Velocity at `current`, in flow units per second. */
  velocity: WorldPoint;
  startMs: number;
  active: boolean;
}

const AT_REST: WorldPoint = { x: 0, y: 0 };

export function createCardSettle(origin: WorldPoint): CardSettleState {
  return {
    origin: { ...origin },
    originVelocity: { ...AT_REST },
    to: { ...origin },
    current: { ...origin },
    velocity: { ...AT_REST },
    startMs: 0,
    active: false,
  };
}

function landed(state: CardSettleState): CardSettleState {
  return {
    ...state,
    current: { ...state.to },
    velocity: { ...AT_REST },
    active: false,
  };
}

/** One axis of `x(t) = to + (d + (v + ωd)t)e^(-ωt)` and its derivative. */
function springAxis(
  from: number,
  velocity: number,
  to: number,
  seconds: number,
): [number, number] {
  const offset = from - to;
  const slope = velocity + SETTLE_OMEGA * offset;
  const decay = Math.exp(-SETTLE_OMEGA * seconds);
  return [
    to + (offset + slope * seconds) * decay,
    (velocity - SETTLE_OMEGA * slope * seconds) * decay,
  ];
}

/** Where the settle is at `nowMs`; inactive once the card has arrived. */
export function stepCardSettle(
  state: CardSettleState,
  nowMs: number,
): CardSettleState {
  if (!state.active) return state;
  const elapsedMs = Math.max(nowMs - state.startMs, 0);
  if (elapsedMs >= SETTLE_MAX_DURATION_MS) return landed(state);
  const seconds = elapsedMs / 1000;
  const [x, vx] = springAxis(
    state.origin.x,
    state.originVelocity.x,
    state.to.x,
    seconds,
  );
  const [y, vy] = springAxis(
    state.origin.y,
    state.originVelocity.y,
    state.to.y,
    seconds,
  );
  if (
    Math.hypot(state.to.x - x, state.to.y - y) < SETTLE_REST_DISTANCE &&
    Math.hypot(vx, vy) < SETTLE_REST_SPEED
  ) {
    return landed(state);
  }
  return { ...state, current: { x, y }, velocity: { x: vx, y: vy } };
}

/**
 * Glide towards a new target from wherever the card is drawn at `nowMs`,
 * keeping its velocity so a fast multi-cell drag flows without stalling at
 * each grid line.
 */
export function retargetCardSettle(
  state: CardSettleState,
  nextTarget: WorldPoint,
  nowMs: number,
): CardSettleState {
  const { current, velocity } = stepCardSettle(state, nowMs);
  const next: CardSettleState = {
    origin: { ...current },
    originVelocity: { ...velocity },
    to: { ...nextTarget },
    current: { ...current },
    velocity: { ...velocity },
    startMs: nowMs,
    active: true,
  };
  // A hop too small to see, from rest, lands at once so a resting card is exact.
  const distance = Math.hypot(
    nextTarget.x - current.x,
    nextTarget.y - current.y,
  );
  const speed = Math.hypot(velocity.x, velocity.y);
  return distance < SETTLE_REST_DISTANCE && speed < SETTLE_REST_SPEED
    ? landed(next)
    : next;
}
