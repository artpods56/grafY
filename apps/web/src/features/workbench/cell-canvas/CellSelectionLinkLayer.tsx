"use client";

import { Fragment, type ReactElement } from "react";
import * as stylex from "@stylexjs/stylex";

import { tokens } from "@/lib/stylex/tokens.stylex";

import { cardWorldRect, type CellCardModel } from "./cell-model";

export interface CellSelectionLinkLine {
  id: string;
  sourceCardId: string;
  targetCardId: string;
}

const s = stylex.create({
  svg: {
    position: "absolute",
    left: 0,
    top: 0,
    width: "1px",
    height: "1px",
    overflow: "visible",
    pointerEvents: "none",
  },
  stroke: {
    stroke: tokens.colorAccent,
  },
  end: {
    fill: tokens.colorAccent,
  },
});

function linkEnds(
  source: { x: number; y: number; width: number; height: number },
  target: { x: number; y: number; width: number; height: number },
): { x1: number; y1: number; x2: number; y2: number } {
  const sourceCenterX = source.x + source.width / 2;
  const sourceCenterY = source.y + source.height / 2;
  const targetCenterX = target.x + target.width / 2;
  const targetCenterY = target.y + target.height / 2;
  if (
    Math.abs(targetCenterX - sourceCenterX) >=
    Math.abs(targetCenterY - sourceCenterY)
  ) {
    const targetIsRight = targetCenterX > sourceCenterX;
    return {
      x1: targetIsRight ? source.x + source.width : source.x,
      y1: sourceCenterY,
      x2: targetIsRight ? target.x : target.x + target.width,
      y2: targetCenterY,
    };
  }
  const targetIsBelow = targetCenterY > sourceCenterY;
  return {
    x1: sourceCenterX,
    y1: targetIsBelow ? source.y + source.height : source.y,
    x2: targetCenterX,
    y2: targetIsBelow ? target.y : target.y + target.height,
  };
}

export function CellSelectionLinkLayer(props: {
  cards: readonly CellCardModel[];
  lines: readonly CellSelectionLinkLine[];
}): ReactElement | null {
  const drawn = props.lines.flatMap((line) => {
    const source = props.cards.find((card) => card.id === line.sourceCardId);
    const target = props.cards.find((card) => card.id === line.targetCardId);
    if (source == null || target == null) return [];
    return [
      {
        id: line.id,
        ends: linkEnds(cardWorldRect(source), cardWorldRect(target)),
      },
    ];
  });
  if (drawn.length === 0) return null;
  return (
    <svg
      aria-hidden="true"
      data-selection-links="true"
      {...stylex.props(s.svg)}
    >
      {drawn.map(({ id, ends }) => (
        <Fragment key={id}>
          <line
            data-selection-link={id}
            x1={ends.x1}
            y1={ends.y1}
            x2={ends.x2}
            y2={ends.y2}
            strokeOpacity={0.75}
            strokeWidth={1.5}
            strokeDasharray="5 5"
            vectorEffect="non-scaling-stroke"
            strokeLinecap="round"
            {...stylex.props(s.stroke)}
          />
          <circle cx={ends.x2} cy={ends.y2} r={3} {...stylex.props(s.end)} />
        </Fragment>
      ))}
    </svg>
  );
}
