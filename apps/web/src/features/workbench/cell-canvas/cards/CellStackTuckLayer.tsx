"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";

import { tokens } from "@/lib/stylex/tokens.stylex";

import {
  cellCornerRadius,
  type CellCorners,
  type CellStackStyle,
} from "../cell-glass-stage";
import {
  CARD_PLATE_BOTTOM_INSET,
  CARD_PLATE_INSET_X,
  CARD_PLATE_TOP,
  CELL_SIZE,
  type WorldPoint,
} from "../cell-model";
import {
  createCardSettle,
  retargetCardSettle,
  stepCardSettle,
  type CardSettleState,
} from "../cell-transitions";
import { stackBackTransform } from "./CellArtifactCard";
import { styled } from "./CellOperatorCard";

/**
 * A card joining a stack, drawn for the moment it takes to slide under the
 * stack's top card into a back's place. The canvas hides the real card while
 * its tuck runs; the merged stack then shows the back for good.
 */
export interface StackTuck {
  id: string;
  /** The card being tucked away, hidden on the canvas while this runs. */
  cardId: string;
  /** Its card box's world origin where it was let go. */
  from: WorldPoint;
  fromWidthCells: number;
  fromHeightCells: number;
  /** The stack's top card box's world origin. */
  to: WorldPoint;
  toWidthCells: number;
  toHeightCells: number;
  imageUrl: string | null;
  /** Which back it becomes: 0 nearest the plate. */
  slot: number;
  stackStyle: CellStackStyle;
  corners: CellCorners;
}

// StyleX evaluates these at build time, so they are plain strings, not calls.
const TUCK_SHADOW =
  "0 1px 2px light-dark(color-mix(in srgb, black 10%, transparent), color-mix(in srgb, black 45%, transparent))";

const s = stylex.create({
  tuck: {
    position: "absolute",
    top: 0,
    left: 0,
    // Under every resting card (they sit at 1), so it slides beneath its
    // stack's top instead of over it.
    zIndex: 0,
    boxSizing: "border-box",
    overflow: "hidden",
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    backgroundColor: tokens.colorSurfaceRaised,
    boxShadow: TUCK_SHADOW,
    pointerEvents: "none",
    willChange: "transform",
  },
  image: {
    position: "absolute",
    inset: 0,
    width: "100%",
    height: "100%",
    objectFit: "cover",
    opacity: 0.55,
    pointerEvents: "none",
    userSelect: "none",
  },
});

function lerp(from: number, to: number, t: number): number {
  return from + (to - from) * t;
}

/** How far along its glide a tuck is, 0 where it left to 1 at its back. */
function tuckProgress(tuck: StackTuck, settle: CardSettleState): number {
  const total = Math.hypot(tuck.to.x - tuck.from.x, tuck.to.y - tuck.from.y);
  if (total < 0.5 || !settle.active) return 1;
  const left = Math.hypot(
    tuck.to.x - settle.current.x,
    tuck.to.y - settle.current.y,
  );
  return Math.max(0, Math.min(1, 1 - left / total));
}

/**
 * Draws each running tuck and springs it from where it was let go into its
 * back's place under the stack, calling `onSettled` once it lands.
 */
export function CellStackTuckLayer({
  tucks,
  onSettled,
}: {
  tucks: readonly StackTuck[];
  onSettled: (id: string) => void;
}) {
  const settlesRef = React.useRef(new Map<string, CardSettleState>());
  const frameRef = React.useRef(0);
  const onSettledRef = React.useRef(onSettled);
  // What the last frame drew, by tuck; a tuck not in it yet sits where it
  // was let go.
  const [drawn, setDrawn] = React.useState<
    ReadonlyMap<string, CardSettleState>
  >(() => new Map());

  React.useLayoutEffect(() => {
    onSettledRef.current = onSettled;
  });

  React.useLayoutEffect(() => {
    const settles = settlesRef.current;
    const now = performance.now();
    const live = new Set(tucks.map((tuck) => tuck.id));
    for (const id of settles.keys()) {
      if (!live.has(id)) settles.delete(id);
    }
    for (const tuck of tucks) {
      if (settles.has(tuck.id)) continue;
      settles.set(
        tuck.id,
        retargetCardSettle(createCardSettle(tuck.from), tuck.to, now),
      );
    }
    if (tucks.length === 0 || frameRef.current !== 0) return;
    const tick = () => {
      frameRef.current = 0;
      const at = performance.now();
      const landed: string[] = [];
      for (const [id, settle] of settles) {
        const stepped = stepCardSettle(settle, at);
        settles.set(id, stepped);
        if (!stepped.active) landed.push(id);
      }
      setDrawn(new Map(settles));
      for (const id of landed) onSettledRef.current(id);
      if (landed.length < settles.size) {
        frameRef.current = requestAnimationFrame(tick);
      }
    };
    frameRef.current = requestAnimationFrame(tick);
  }, [tucks]);

  React.useEffect(
    () => () => {
      if (frameRef.current !== 0) cancelAnimationFrame(frameRef.current);
      frameRef.current = 0;
    },
    [],
  );

  return tucks.map((tuck) => {
    const settle = drawn.get(tuck.id);
    const at = settle?.current ?? tuck.from;
    const t = settle ? tuckProgress(tuck, settle) : 0;
    const width = lerp(tuck.fromWidthCells, tuck.toWidthCells, t) * CELL_SIZE;
    const height =
      lerp(tuck.fromHeightCells, tuck.toHeightCells, t) * CELL_SIZE;
    const pose = stackBackTransform(
      { widthCells: tuck.toWidthCells, heightCells: tuck.toHeightCells },
      tuck.stackStyle,
      tuck.slot,
      t,
    );
    return (
      <span
        key={tuck.id}
        aria-hidden="true"
        data-stack-tuck={tuck.cardId}
        data-stack-tuck-slot={tuck.slot + 1}
        data-stack-tuck-style={tuck.stackStyle}
        {...styled(
          {
            width: width - CARD_PLATE_INSET_X * 2,
            height: height - CARD_PLATE_TOP - CARD_PLATE_BOTTOM_INSET,
            borderRadius: cellCornerRadius(tuck.corners),
            transform: `translate3d(${at.x + CARD_PLATE_INSET_X}px, ${at.y + CARD_PLATE_TOP}px, 0) ${pose.transform}`,
            transformOrigin: pose.transformOrigin,
          },
          s.tuck,
        )}
      >
        {tuck.imageUrl ? (
          // eslint-disable-next-line @next/next/no-img-element -- artifact bytes have no predictable size for the image optimizer
          <img
            src={tuck.imageUrl}
            alt=""
            draggable={false}
            {...stylex.props(s.image)}
          />
        ) : null}
      </span>
    );
  });
}
