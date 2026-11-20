import { Position } from "@xyflow/react";

import type { CardRect, PipeRequest, RoutingScene } from "../pipe-routing";

/**
 * Scenes for the router tests, shaped like the spike's graphs: a port ring
 * sits 23 units outside its card, outputs on the right and inputs on the left.
 */

export function pipe(
  id: string,
  source: [number, number],
  target: [number, number],
): PipeRequest {
  return {
    id,
    source: { x: source[0], y: source[1] },
    sourceSide: Position.Right,
    target: { x: target[0], y: target[1] },
    targetSide: Position.Left,
  };
}

export function card(
  id: string,
  x: number,
  y: number,
  width = 300,
  height = 194,
): CardRect {
  return { id, x, y, width, height };
}

/** The spike's demo: three cards, one pipe forward and one doubling back. */
export const DEMO_SCENE: RoutingScene = {
  cards: [
    card("import", 0, 0),
    card("summarize", 420, 200),
    card("render", 40, 420, 300, 215),
  ],
  pipes: [
    pipe("pipe-table", [323, 50], [397, 328]),
    pipe("pipe-report", [743, 250], [17, 498]),
  ],
};

const STEP = { x: 440, y: 380 };
const SIZE = { width: 300, height: 290 };

function output(column: number, row: number): [number, number] {
  return [column * STEP.x + SIZE.width + 23, row * STEP.y + 50];
}

function input(column: number, row: number, slot: number): [number, number] {
  return [column * STEP.x - 23, row * STEP.y + 128 + slot * 48];
}

/**
 * The stress grid, smaller: each card is fed by its left neighbour and both
 * upper diagonals, so a third of the pipes double back.
 */
export function gridScene(columns: number, rows: number): RoutingScene {
  const cards: CardRect[] = [];
  const pipes: PipeRequest[] = [];
  for (let row = 0; row < rows; row += 1) {
    for (let column = 0; column < columns; column += 1) {
      const id = `${row}-${column}`;
      cards.push(
        card(id, column * STEP.x, row * STEP.y, SIZE.width, SIZE.height),
      );
      const feeds: [string, number, number][] = [
        ["left", column - 1, row],
        ["up-left", column - 1, row - 1],
        ["up-right", column + 1, row - 1],
      ];
      for (const [slot, [name, fromColumn, fromRow]] of feeds.entries()) {
        if (fromColumn < 0 || fromRow < 0 || fromColumn >= columns) continue;
        pipes.push(
          pipe(
            `${id}-${name}`,
            output(fromColumn, fromRow),
            input(column, row, slot),
          ),
        );
      }
    }
  }
  return { cards, pipes };
}

/** The scene with one card, and every port on it, moved by `dx, dy`. */
export function moveCard(
  scene: RoutingScene,
  id: string,
  dx: number,
  dy: number,
): RoutingScene {
  const moved = scene.cards.find((candidate) => candidate.id === id);
  if (!moved) return scene;
  const onCard = (point: { x: number; y: number }) =>
    point.x >= moved.x - 30 &&
    point.x <= moved.x + moved.width + 30 &&
    point.y >= moved.y &&
    point.y <= moved.y + moved.height;
  const shift = (point: { x: number; y: number }) =>
    onCard(point) ? { x: point.x + dx, y: point.y + dy } : point;
  return {
    cards: scene.cards.map((candidate) =>
      candidate.id === id
        ? { ...candidate, x: candidate.x + dx, y: candidate.y + dy }
        : candidate,
    ),
    pipes: scene.pipes.map((request) => ({
      ...request,
      source: shift(request.source),
      target: shift(request.target),
    })),
  };
}
