import { Position } from "@xyflow/react";

/**
 * What a pipe router is given and what it returns. The routers themselves
 * live in `./routing/`, one file each, and the panel switches between them.
 *
 * A router sees every pipe's two ports and every card's rectangle, and returns
 * each pipe's corner points and the layer under the glass it lies on. It routes
 * all pipes together, so that pipes sharing a channel can run side by side.
 *
 * The port stub contract: every route leaves its source port, and enters its
 * target port, straight and perpendicular to the card side for at least
 * {@link PIPE_STUB_MIN}. The wells and risers draw that stretch themselves and
 * assume it; `routing/contract.test.ts` checks it for every router.
 */

export interface Point {
  x: number;
  y: number;
}

export interface PipeRequest {
  id: string;
  /** Centre of the source port's ring, and the side of the card it sits on. */
  source: Point;
  sourceSide: Position;
  target: Point;
  targetSide: Position;
}

/** A card's rectangle, in flow units. */
export interface CardRect {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface RoutingScene {
  pipes: readonly PipeRequest[];
  /**
   * Pipes lie under the glass, so a card is no wall: a router may run a pipe
   * under one, or prefer the gaps between them.
   */
  cards: readonly CardRect[];
}

export interface RoutingOptions {
  /** Spread pipes that share a channel into lanes side by side. */
  lanes: boolean;
  /** Sink pipes a channel cannot hold into deeper layers. */
  depth: boolean;
}

export interface RoutedPipe {
  /** Corner points, the source port first and the target port last. */
  points: Point[];
  /** 0 is just under the glass; higher layers lie deeper. */
  depth: number;
}

/**
 * Routes a whole scene. It may remember the layout it returned last time, to
 * keep a pipe's shape steady while a card moves, but routing the same scene
 * twice in a row gives the same layout.
 */
export type SceneRouter = (
  scene: RoutingScene,
  options: RoutingOptions,
) => Map<string, RoutedPipe>;

export interface PipeRoutingBackend {
  /** Stable id, kept in the look. */
  id: string;
  /** Its name in the panel. */
  label: string;
  /** The options it honours; the panel disables the others. */
  supports: Readonly<RoutingOptions>;
  /** `orthogonal` routes turn at right angles; `octilinear` ones also run at 45°. */
  angles: "orthogonal" | "octilinear";
  /** A router for one canvas. The moving and the resting pipes share it. */
  create(): SceneRouter;
}

/** How far a pipe runs straight out of its port before its first bend. */
export const PIPE_STUB = 30;
/** The shortest a stub may get when its bend is moved into a lane. */
export const PIPE_STUB_MIN = 27;
/** Distance between the centre lines of two pipes sharing a channel. */
export const PIPE_LANE = 14;
/** The tightest lanes may get in a narrow channel before pipes sink deeper. */
export const PIPE_LANE_MIN = 10;
/** The deepest layer a pipe may sink to. */
export const PIPE_MAX_DEPTH = 2;

/** The unit direction a pipe leaves a port on this side of its card. */
export function outward(side: Position): Point {
  switch (side) {
    case Position.Left:
      return { x: -1, y: 0 };
    case Position.Right:
      return { x: 1, y: 0 };
    case Position.Top:
      return { x: 0, y: -1 };
    case Position.Bottom:
      return { x: 0, y: 1 };
  }
}

/**
 * SVG path through the points, with square or rounded bends. Segments may run
 * at any angle: a bend between a straight and a diagonal stretch rounds the
 * same way as a right angle.
 */
export function pipePath(points: readonly Point[], radius: number): string {
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
    const bend = Math.min(radius, inLength / 2, outLength / 2);
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
