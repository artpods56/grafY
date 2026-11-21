import { Position } from "@xyflow/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PipeRequest, Point } from "../pipe-routing";
import {
  anchor,
  interpolateRoute,
  matchPoints,
  PipeTransition,
  ROUTE_DWELL_MS,
  ROUTE_MORPH_MS,
  routeKey,
  toPath,
  type RoutedPath,
} from "./route-transitions";

const pipe: PipeRequest = {
  id: "p",
  source: { x: 0, y: 0 },
  sourceSide: Position.Right,
  target: { x: 180, y: 80 },
  targetSide: Position.Left,
};
const elbow = [pipe.source, { x: 80, y: 0 }, { x: 80, y: 80 }, pipe.target];
const loop = [
  pipe.source,
  { x: 210, y: 0 },
  { x: 210, y: 40 },
  { x: 130, y: 40 },
  { x: 130, y: 80 },
  pipe.target,
];
const radius = 12;
const original = { key: "elbow", path: toPath(elbow, 0, radius) };

function fixture() {
  const show = vi.fn<(path: RoutedPath) => void>();
  const transition = new PipeTransition(original, show, vi.fn());
  function update(
    key: string,
    points: Point[],
    { ports = pipe, morph = false, dwell = true, depth = 0 } = {},
  ) {
    const path = toPath(points, depth, radius);
    transition.update({
      destination: { key, path },
      pipe: ports,
      radius,
      dwell,
      morph,
    });
    return path;
  }
  return { show, update, transition };
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("route dwell", () => {
  it("ignores a candidate that flickers and accepts one that survives a pause", () => {
    const { show, update } = fixture();
    const candidate = update("loop", loop);
    vi.advanceTimersByTime(ROUTE_DWELL_MS - 1);
    expect(show).not.toHaveBeenCalledWith(candidate);
    update("elbow", elbow);
    vi.advanceTimersByTime(ROUTE_DWELL_MS);
    expect(show).not.toHaveBeenCalledWith(candidate);

    update("loop", loop);
    vi.advanceTimersByTime(ROUTE_DWELL_MS);
    expect(show).toHaveBeenLastCalledWith(candidate);
  });

  it("restarts for a different candidate and keeps the latest geometry", () => {
    const { show, update } = fixture();
    const first = update("loop", loop);
    vi.advanceTimersByTime(200);
    update("deep", loop, { depth: 1 });
    vi.advanceTimersByTime(100);
    const moved = loop.map((point) =>
      point.x === 210 ? { ...point, x: 220 } : point,
    );
    const latest = update("deep", moved, { depth: 1 });
    expect(show).not.toHaveBeenCalledWith(first);
    expect(show).not.toHaveBeenCalledWith(latest);
    vi.advanceTimersByTime(150);
    expect(show).toHaveBeenLastCalledWith(latest);
  });

  it("passes a continuous stretch straight through", () => {
    const { show, update } = fixture();
    const stretched = [
      pipe.source,
      { x: 85, y: 0 },
      { x: 85, y: 80 },
      pipe.target,
    ];
    expect(routeKey({ points: elbow, depth: 0 })).toBe(
      routeKey({ points: stretched, depth: 0 }),
    );
    const path = update("elbow", stretched);
    expect(show).toHaveBeenLastCalledWith(path);
  });

  it("moves only the port approaches while a different route waits", () => {
    const { transition, update } = fixture();
    const source = { x: 10, y: 15 };
    update("loop", [source, ...loop.slice(1)], { ports: { ...pipe, source } });
    expect(transition.shown.points).toEqual([
      source,
      { x: 80, y: 15 },
      { x: 80, y: 80 },
      pipe.target,
    ]);
    transition.stop();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("keeps a held straight pipe from folding when its ports move off-axis", () => {
    const target = { x: 180, y: 0 };
    const source = { x: 10, y: 15 };
    expect(anchor([pipe.source, target], { ...pipe, source, target })).toEqual([
      source,
      { x: 95, y: 15 },
      { x: 95, y: 0 },
      target,
    ]);
  });

  it("distinguishes lane, corridor and depth changes without using coordinates", () => {
    const route = {
      points: elbow,
      lanes: ".1",
      channel: "left/right",
      depth: 0,
    };
    const keys = [
      route,
      { ...route, lanes: ".2" },
      { ...route, channel: "right/far" },
      { ...route, depth: 1 },
      { ...route, points: loop },
      { ...route, points: elbow.toReversed() },
    ].map(routeKey);
    expect(new Set(keys).size).toBe(keys.length);
  });
});

describe("route morph", () => {
  it("matches samples, pins both ports, and uses the exact endpoint paths", () => {
    const from = original.path;
    const to = toPath(loop, 2, radius);
    const matched = matchPoints(from.points, to.points);
    expect(matched[0]).toHaveLength(matched[1].length);
    expect(interpolateRoute(from, to, matched, 0, radius)).toEqual(from);
    expect(interpolateRoute(from, to, matched, 1, radius)).toEqual(to);
    for (const progress of [0.1, 0.49, 0.5, 0.8]) {
      const frame = interpolateRoute(from, to, matched, progress, radius);
      expect(frame.points).toHaveLength(matched[0].length);
      expect(frame.points[0]).toEqual(pipe.source);
      expect(frame.points.at(-1)).toEqual(pipe.target);
      expect(frame.depth).toBe(progress < 0.5 ? 0 : 2);
      expect(frame.path).toContain("Q");
    }
  });

  it("interrupts from the last published shape and keeps moving ports attached", () => {
    const { transition, update } = fixture();
    update("loop", loop, { morph: true, dwell: false });
    vi.advanceTimersByTime(50);
    expect(transition.frame(performance.now())).toBe(true);
    const midpoint = transition.shown;
    update("other", elbow, { morph: true, dwell: false });
    expect(transition.shown).toEqual(midpoint);

    const source = { x: 15, y: 20 };
    const moved = [source, { x: 80, y: 20 }, ...elbow.slice(2)];
    const final = update("other", moved, {
      ports: { ...pipe, source },
      morph: true,
      dwell: false,
    });
    expect(transition.shown.points[0]).toEqual(source);
    expect(transition.shown.points.at(-1)).toEqual(pipe.target);
    vi.advanceTimersByTime(ROUTE_MORPH_MS);
    expect(transition.frame(performance.now())).toBe(false);
    expect(transition.shown).toEqual(final);
  });
});
