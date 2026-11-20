import { Position } from "@xyflow/react";

import {
  PIPE_STUB,
  PIPE_STUB_MIN,
  type PipeRequest,
  type Point,
  type RoutingScene,
} from "../pipe-routing";

/**
 * Which way a pipe leaves its well. A port is a well and the pipe rises
 * straight up through it, so under the glass the pipe may leave in any
 * direction. `side` keeps the card side the port sits on. `free` keeps it
 * while the other end lies ahead, and otherwise turns both ends up or down:
 * a target behind its source, or nearly straight above or below it, then
 * needs no loop back and no S-bend.
 */
export type PipeExits = "side" | "free";

/**
 * How a pipe's two ends leave their wells: along the card side, or apart
 * (the source down and the target up, or the reverse), or both the same way.
 */
export type ExitShape = "side" | "apart-down" | "apart-up" | "under" | "over";

/** How far ahead the target must lie for a pipe to leave along the side. */
const AHEAD = PIPE_STUB_MIN * 2;
/** How far apart the ends must lie for them to leave toward each other. */
const APART = PIPE_STUB * 2;
/** A pipe changes shape only once its ends move this far past the line. */
const STICK = 20;
/** Ports closer than this across a column sit in each other's way. */
const COLUMN = 16;

/**
 * The shape for a pipe from a right-side output to a left-side input, whose
 * target lies `ahead` to the right of its source and `below` it. The previous
 * shape is kept until the ends have moved {@link STICK} past the line, so a
 * dragged pipe does not flicker between shapes.
 */
export function exitShape(
  ahead: number,
  below: number,
  previous?: ExitShape,
): ExitShape {
  const wasSide = previous === undefined || previous === "side";
  if (ahead >= AHEAD + (wasSide ? 0 : STICK)) return "side";
  if (below >= APART + (previous === "apart-down" ? 0 : STICK)) {
    return "apart-down";
  }
  if (-below >= APART + (previous === "apart-up" ? 0 : STICK)) {
    return "apart-up";
  }
  if (previous === "under" && below > -STICK) return "under";
  if (previous === "over" && below < STICK) return "over";
  if (previous === "apart-down") return "under";
  if (previous === "apart-up") return "over";
  return below >= 0 ? "under" : "over";
}

const SIDES: Record<ExitShape, [Position, Position] | null> = {
  side: null,
  "apart-down": [Position.Bottom, Position.Top],
  "apart-up": [Position.Top, Position.Bottom],
  under: [Position.Bottom, Position.Bottom],
  over: [Position.Top, Position.Top],
};

/**
 * True when leaving `port` straight up (`way` -1) or down (1) for `reach`
 * would run under another port's well, as it would from a stack of inputs.
 */
function blocked(
  port: Point,
  way: number,
  reach: number,
  ports: readonly Point[],
): boolean {
  for (const other of ports) {
    if (Math.abs(other.x - port.x) >= COLUMN) continue;
    const ahead = (other.y - port.y) * way;
    if (ahead > 0.5 && ahead < reach) return true;
  }
  return false;
}

/** A side that leaves up or down, as -1 or 1; 0 for any other. */
function vertical(side: Position): number {
  if (side === Position.Top) return -1;
  if (side === Position.Bottom) return 1;
  return 0;
}

/**
 * The scene with each pipe's sides replaced by the way it leaves its wells,
 * and the shapes chosen, for the next call's `previous`. Only right-to-left
 * pipes change: they are the only kind on this canvas. An end whose way up or
 * down runs under another port keeps its side.
 */
export function withExits(
  scene: RoutingScene,
  exits: PipeExits,
  previous: ReadonlyMap<string, ExitShape> = new Map(),
): { scene: RoutingScene; shapes: Map<string, ExitShape> } {
  const shapes = new Map<string, ExitShape>();
  if (exits === "side") return { scene, shapes };
  const ports = scene.pipes.flatMap((pipe) => [pipe.source, pipe.target]);
  const pipes = scene.pipes.map((pipe): PipeRequest => {
    if (
      pipe.sourceSide !== Position.Right ||
      pipe.targetSide !== Position.Left
    ) {
      return pipe;
    }
    const shape = exitShape(
      pipe.target.x - pipe.source.x,
      pipe.target.y - pipe.source.y,
      previous.get(pipe.id),
    );
    shapes.set(pipe.id, shape);
    const sides = SIDES[shape];
    if (!sides) return pipe;
    const reach = Math.abs(pipe.target.y - pipe.source.y) + PIPE_STUB * 2;
    const [sourceSide, targetSide] = sides;
    return {
      ...pipe,
      sourceSide: blocked(pipe.source, vertical(sourceSide), reach, ports)
        ? pipe.sourceSide
        : sourceSide,
      targetSide: blocked(pipe.target, vertical(targetSide), reach, ports)
        ? pipe.targetSide
        : targetSide,
    };
  });
  return { scene: { ...scene, pipes }, shapes };
}
