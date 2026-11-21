import {
  PIPE_STUB_MIN,
  outward,
  pipePath,
  type PipeRequest,
  type Point,
  type RoutedPipe,
} from "../pipe-routing";

export const ROUTE_DWELL_MS = 250;
export const ROUTE_MORPH_MS = 150;

export interface RoutedPath {
  path: string;
  points: readonly Point[];
  depth: number;
}

export function routeKey(route: RoutedPipe): string {
  return `${route.depth}:${route.channel ?? ""}:${route.lanes ?? ""}:${directions(route.points)}`;
}

export function directions(points: readonly Point[]): string {
  let key = "";
  for (let i = 1; i < points.length; i += 1) {
    const a = points[i - 1];
    const b = points[i];
    if (!a || !b) continue;
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    key += String(4 + 3 * direction(dx) + direction(dy));
  }
  return key;
}

function direction(delta: number): number {
  return Math.abs(delta) < 1e-6 ? 0 : Math.sign(delta);
}

export function toPath(
  points: readonly Point[],
  depth: number,
  radius: number,
): RoutedPath {
  return { points, depth, path: pipePath(points, radius) };
}

function samePoint(a: Point | undefined, b: Point): boolean {
  return a?.x === b.x && a.y === b.y;
}

/** Intersect the moved stub with the line of the first retained stretch. */
function portBend(port: Point, out: Point, bend: Point, next: Point): Point {
  const across = -out.y * (next.x - bend.x) + out.x * (next.y - bend.y);
  const shift = -out.y * (port.x - bend.x) + out.x * (port.y - bend.y);
  const along = out.x * (next.x - bend.x) + out.y * (next.y - bend.y);
  const at =
    Math.abs(across) > Math.max(1e-6, Math.abs(along) / 2) ? shift / across : 0;
  const x = bend.x + at * (next.x - bend.x);
  const y = bend.y + at * (next.y - bend.y);
  const length = Math.max(
    PIPE_STUB_MIN,
    (x - port.x) * out.x + (y - port.y) * out.y,
  );
  return { x: port.x + out.x * length, y: port.y + out.y * length };
}

/** Keep the old inner run and move the two stubs with their ports. */
export function anchor(
  points: readonly Point[],
  pipe: PipeRequest,
): readonly Point[] {
  const { source, target, sourceSide, targetSide } = pipe;
  if (samePoint(points[0], source) && samePoint(points.at(-1), target)) {
    return points;
  }

  const start = outward(sourceSide);
  const end = outward(targetSide);
  const mid = lerp(source, target, 0.5);
  const first = points.length === 2 ? mid : (points[1] ?? source);
  const last = points.length === 2 ? mid : (points.at(-2) ?? target);
  // A straight route can stretch along its axis without introducing bends.
  if (
    points.length === 2 &&
    (target.x - source.x) * start.y === (target.y - source.y) * start.x &&
    (target.x - source.x) * start.x + (target.y - source.y) * start.y >=
      PIPE_STUB_MIN * 2
  ) {
    return [source, target];
  }
  return [
    source,
    portBend(source, start, first, points[2] ?? first),
    ...points.slice(2, -2),
    portBend(target, end, last, points.at(-3) ?? last),
    target,
  ];
}

/** Normalize the distances at each corner so either route can be sampled. */
function knots(points: readonly Point[]): number[] {
  const distances = [0];
  let length = 0;
  for (let i = 1; i < points.length; i += 1) {
    const a = points[i - 1];
    const b = points[i];
    if (a && b) length += Math.hypot(b.x - a.x, b.y - a.y);
    distances.push(length);
  }
  return length > 0 ? distances.map((distance) => distance / length) : [0, 1];
}

function lerp(a: Point, b: Point, t: number): Point {
  return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t };
}

function sample(
  points: readonly Point[],
  distances: readonly number[],
  at: readonly number[],
): Point[] {
  let index = 1;
  return at.map((fraction) => {
    while (index < distances.length - 1 && (distances[index] ?? 1) < fraction) {
      index += 1;
    }
    const a = points[index - 1] ?? points[0] ?? { x: 0, y: 0 };
    const b = points[index] ?? a;
    const low = distances[index - 1] ?? 0;
    const high = distances[index] ?? 1;
    return lerp(a, b, high > low ? (fraction - low) / (high - low) : 0);
  });
}

function stubbed(points: readonly Point[]): readonly Point[] {
  const [source, target] = points;
  if (points.length !== 2 || !source || !target) return points;
  const length = Math.hypot(target.x - source.x, target.y - source.y);
  const stub = Math.min(PIPE_STUB_MIN / length, 0.5);
  return [
    source,
    lerp(source, target, stub),
    lerp(target, source, stub),
    target,
  ];
}

export function matchPoints(
  from: readonly Point[],
  to: readonly Point[],
): readonly [readonly Point[], readonly Point[]] {
  if (directions(from) === directions(to)) return [from, to];
  const start = stubbed(from);
  const end = stubbed(to);
  const fromRun = start.slice(1, -1);
  const toRun = end.slice(1, -1);
  const fromKnots = knots(fromRun);
  const toKnots = knots(toRun);
  // Sample both inner runs at their corners. Match the port stubs directly
  // so the fittings stay straight and attached as the rest of the pipe bends.
  const at = [...new Set([...fromKnots, ...toKnots])].sort((a, b) => a - b);
  const samples =
    at.length <= 24 ? at : Array.from({ length: 24 }, (_, index) => index / 23);
  const fromPort = start[0];
  const fromEnd = start.at(-1);
  const toPort = end[0];
  const toEnd = end.at(-1);
  if (!fromPort || !fromEnd || !toPort || !toEnd) return [from, to];
  return [
    [fromPort, ...sample(fromRun, fromKnots, samples), fromEnd],
    [toPort, ...sample(toRun, toKnots, samples), toEnd],
  ];
}

export function interpolateRoute(
  from: RoutedPath,
  to: RoutedPath,
  matched: ReturnType<typeof matchPoints>,
  progress: number,
  radius: number,
): RoutedPath {
  if (progress <= 0) return from;
  if (progress >= 1) return to;
  const [start, end] = matched;
  const eased = 1 - (1 - progress) ** 3;
  const points = start.map((point, index) =>
    lerp(point, end[index] ?? point, eased),
  );
  return toPath(points, progress < 0.5 ? from.depth : to.depth, radius);
}

interface Destination {
  key: string;
  path: RoutedPath;
}

interface Update {
  destination: Destination;
  pipe: PipeRequest;
  radius: number;
  dwell: boolean;
  morph: boolean;
  settle?: boolean;
}

interface Pending {
  update: Update;
  timer: ReturnType<typeof setTimeout>;
}

interface Morph {
  from: RoutedPath;
  to: RoutedPath;
  points: ReturnType<typeof matchPoints>;
  start: number;
  radius: number;
}

export class PipeTransition {
  private accepted: Destination;
  private pending: Pending | undefined;
  private animation: Morph | undefined;
  private readonly show: (path: RoutedPath) => void;
  private readonly animate: (transition: PipeTransition) => void;
  shown: RoutedPath;

  constructor(
    initial: Destination,
    show: (path: RoutedPath) => void,
    animate: (transition: PipeTransition) => void,
    shown = initial.path,
  ) {
    this.accepted = initial;
    this.show = show;
    this.animate = animate;
    this.shown = shown;
  }

  update(update: Update): void {
    const { destination, pipe, radius, dwell, morph } = update;
    if (
      (update.settle && morph) ||
      (!dwell && destination.key !== this.accepted.key)
    ) {
      this.clearPending();
      this.accept(update);
      return;
    }

    if (destination.key === this.accepted.key) {
      this.clearPending();
      this.accepted = destination;
      this.follow(destination.path, update);
      return;
    }

    if (this.pending?.update.destination.key === destination.key) {
      this.pending.update = update;
    } else {
      this.clearPending();
      this.pending = {
        update,
        timer: setTimeout(() => {
          const pending = this.pending;
          this.pending = undefined;
          if (pending) this.accept(pending.update);
        }, ROUTE_DWELL_MS),
      };
    }

    const { path } = this.accepted;
    this.follow(toPath(anchor(path.points, pipe), path.depth, radius), update);
  }

  private follow(path: RoutedPath, { pipe, radius, morph }: Update): void {
    const animation = this.animation;
    if (!animation || !morph) {
      this.animation = undefined;
      this.publish(path);
      return;
    }
    if (
      animation.to.path === path.path &&
      animation.to.depth === path.depth &&
      animation.radius === radius
    )
      return;

    animation.from = toPath(
      anchor(animation.from.points, pipe),
      animation.from.depth,
      radius,
    );
    animation.to = path;
    animation.points = matchPoints(animation.from.points, path.points);
    animation.radius = radius;
    this.frame(performance.now());
  }

  get animating(): boolean {
    return this.animation !== undefined;
  }

  get destination(): Destination {
    return this.accepted;
  }

  frame(now: number): boolean {
    const animation = this.animation;
    if (!animation) return false;
    const progress = (now - animation.start) / ROUTE_MORPH_MS;
    this.publish(
      interpolateRoute(
        animation.from,
        animation.to,
        animation.points,
        progress,
        animation.radius,
      ),
    );
    if (progress >= 1) this.animation = undefined;
    return this.animation !== undefined;
  }

  stop(): void {
    this.clearPending();
    this.animation = undefined;
  }

  private clearPending(): void {
    if (this.pending) clearTimeout(this.pending.timer);
    this.pending = undefined;
  }

  private accept({ destination, pipe, radius, morph }: Update): void {
    this.accepted = destination;
    const { shown } = this;
    const to = destination.path;
    if (!morph || (shown.path === to.path && shown.depth === to.depth)) {
      this.animation = undefined;
      this.publish(to);
      return;
    }
    const from = toPath(anchor(shown.points, pipe), shown.depth, radius);
    this.animation = {
      from,
      to,
      points: matchPoints(from.points, to.points),
      start: performance.now(),
      radius,
    };
    this.publish(from);
    this.animate(this);
  }

  private publish(path: RoutedPath): void {
    this.shown = path;
    this.show(path);
  }
}
