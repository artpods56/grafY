"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { IconButton } from "@/components/ui/button";
import { tokens } from "@/lib/stylex/tokens.stylex";

// Each layer behind a sequence's front item steps this far right and down.
export const STACK_STEP_X = 12;
export const STACK_STEP_Y = 8;
const STACK_DEPTH = 3;

const s = stylex.create({
  // Floats on the front item's bottom edge, so stepping through a stack never
  // moves the card's head, its rails, or anything hung below the body.
  pager: {
    position: "absolute",
    left: "50%",
    bottom: "6px",
    transform: "translateX(-50%)",
    display: "flex",
    alignItems: "center",
    gap: "2px",
    padding: "2px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: "7px",
    backgroundColor: tokens.colorSurfaceRaised,
    boxShadow: tokens.shadowNode,
    color: tokens.colorText,
    fontSize: tokens.fontSizeXs,
    fontVariantNumeric: "tabular-nums",
    whiteSpace: "nowrap",
    pointerEvents: "auto",
  },
  count: { paddingInline: "3px" },
  // Sits over the front slot, outside the layers: the layers trade places
  // under it, so the button you just pressed keeps its place and its focus.
  overlay: { position: "absolute", left: 0, top: 0, pointerEvents: "none" },
  stack: { position: "relative", width: "100%", boxSizing: "border-box" },
  layer: {
    position: "absolute",
    boxSizing: "border-box",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusSm,
    backgroundColor: tokens.colorSurface,
    boxShadow: tokens.shadowNode,
  },
});

/** One layer of a stack: which item it shows and where it sits. */
export type StackSlot = {
  /** The item's index in the sequence; a stable key across pages. */
  item: number;
  /** 0 is the front; each step is one layer further back. */
  slot: number;
  /**
   * The item just behind the last visible layer, drawn there invisibly so the
   * front item has somewhere to go when it is sent back, and somewhere to come
   * from when it is brought forward again.
   */
  tail: boolean;
};

/**
 * The stack as a ring: paging forward sends the front item to the back and
 * brings the one under it up, so every item keeps its neighbours.
 */
function stackSlots(count: number, front: number): StackSlot[] {
  const depth = Math.min(count, STACK_DEPTH);
  const slots: StackSlot[] = [];
  if (count > depth)
    slots.push({
      item: (front + count - 1) % count,
      slot: depth - 1,
      tail: true,
    });
  for (let slot = 0; slot < depth; slot += 1)
    slots.push({ item: (front + slot) % count, slot, tail: false });
  return slots;
}

const SHUFFLE_EASING = "cubic-bezier(0.22, 1, 0.36, 1)";

/**
 * Animates the layers of a stack (its direct children carrying
 * `data-stack-item`) when the front item changes by one step. The layers are
 * keyed by item, so React has already moved each one to its new slot; this
 * plays the way there. The item sent back swings out to the left and tucks in
 * behind; going back, the rear item swings out and lands on top.
 */
function useStackShuffle(front: number, count: number) {
  const ref = React.useRef<HTMLDivElement>(null);
  const previous = React.useRef({ front, count });
  React.useLayoutEffect(() => {
    const was = previous.current;
    previous.current = { front, count };
    const stack = ref.current;
    if (!stack || was.count !== count || was.front === front || count < 2)
      return;
    if (
      typeof stack.animate !== "function" ||
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
    )
      return;
    const forward = (front - was.front + count) % count === 1;
    const backward = (was.front - front + count) % count === 1;
    // A jump (a reorder, a clamp) just lands; only a step has a way to show.
    if (!forward && !backward) return;

    const depth = Math.min(count, STACK_DEPTH);
    const ringSlot = (item: number, at: number) => (item - at + count) % count;
    const position = (slot: number) => {
      const shown = Math.min(slot, depth - 1);
      return { x: shown * STACK_STEP_X, y: shown * STACK_STEP_Y };
    };
    const opacity = (slot: number) => (slot < depth ? 1 : 0);

    const layers = stack.querySelectorAll<HTMLElement>(
      ":scope > [data-stack-item]",
    );
    for (const layer of layers) {
      const item = Number(layer.dataset.stackItem);
      const from = ringSlot(item, was.front);
      const to = ringSlot(item, front);
      const start = position(from);
      const end = position(to);
      const dx = start.x - end.x;
      const dy = start.y - end.y;
      for (const running of layer.getAnimations()) running.cancel();

      const sentBack = forward && from === 0;
      const broughtUp = !forward && backward && to === 0;
      if (sentBack || broughtUp) {
        // Out to the left, clear of the stack, then into its new place: on
        // top of the others on the way out, under them on the way back in
        // (or the reverse, coming forward).
        // Measured from the front slot, whichever way the layer travels.
        const frontX = sentBack ? dx : 0;
        const frontY = sentBack ? dy : 0;
        const swing = layer.offsetWidth * 0.6;
        const away = `translate(${frontX - swing}px, ${frontY - 6}px) rotate(-5deg)`;
        const over = depth + 1;
        layer.animate(
          [
            {
              offset: 0,
              transform: `translate(${dx}px, ${dy}px)`,
              opacity: opacity(from),
              zIndex: sentBack ? over : 0,
            },
            {
              offset: 0.45,
              transform: away,
              opacity: sentBack ? 1 : 0.85,
              zIndex: sentBack ? over : 0,
            },
            { offset: 0.46, zIndex: sentBack ? 0 : over },
            {
              offset: 1,
              transform: "none",
              opacity: opacity(to),
              zIndex: sentBack ? 0 : over,
            },
          ],
          { duration: 420, easing: SHUFFLE_EASING },
        );
        continue;
      }
      layer.animate(
        [
          {
            transform: `translate(${dx}px, ${dy}px)`,
            // A layer that was not drawn before fades in where it lands.
            opacity: from < depth || from === count - 1 ? opacity(from) : 0,
          },
          { transform: "none", opacity: opacity(to) },
        ],
        { duration: 320, easing: SHUFFLE_EASING },
      );
    }
  }, [front, count]);
  return ref;
}

/**
 * Previous and next for the item at the front of a stack: the stack shows
 * where you are in the run, and the pager moves through it.
 */
export function SequencePager({
  index,
  count,
  name,
  onIndex,
}: {
  index: number;
  count: number;
  /** The front item's name, read on hover. */
  name?: string | null;
  onIndex: (index: number) => void;
}) {
  return (
    <div
      role="group"
      aria-label="Sequence pages"
      title={name ?? undefined}
      className={`nodrag nopan nowheel ${stylex.props(s.pager).className ?? ""}`}
    >
      <IconButton
        label="Previous item"
        size="2xs"
        disabled={index === 0}
        onClick={() => onIndex(index - 1)}
      >
        <ChevronLeft size={12} />
      </IconButton>
      <span {...stylex.props(s.count)}>
        {index + 1} / {count}
      </span>
      <IconButton
        label="Next item"
        size="2xs"
        disabled={index === count - 1}
        onClick={() => onIndex(index + 1)}
      >
        <ChevronRight size={12} />
      </IconButton>
    </div>
  );
}

/** What a layer's root element takes to sit in its slot of the stack. */
export type StackPlace = {
  "data-stack-item": number;
  "aria-hidden"?: true;
  style: React.CSSProperties;
};

/**
 * The one stack every sequence shows, whatever its items are: pictures,
 * markdown, pages, tables, files. The front item sits top-left where the input
 * port is, up to two more step down and right toward the output port, and
 * paging turns the stack like a ring under a pager held over the front slot.
 *
 * The stack owns where each layer sits and how it moves; `renderLayer` owns
 * only what the layer looks like, and spreads `place` on its root element.
 *
 * With `frontHeight` every layer is that tall (a picture, a tile). Without it
 * the front layer sits in flow and sets the height (a text or table body), and
 * the layers behind it match it.
 */
export function ArtifactStack({
  count,
  index,
  frontHeight,
  overlay,
  renderLayer,
}: {
  count: number;
  /** The item at the front. */
  index: number;
  frontHeight?: number;
  /** Drawn over the front item, e.g. its pager. */
  overlay?: React.ReactNode;
  renderLayer: (slot: StackSlot, place: StackPlace) => React.ReactNode;
}) {
  const shuffle = useStackShuffle(index, count);
  const depth = Math.min(count, STACK_DEPTH);
  const spanX = (depth - 1) * STACK_STEP_X;
  const spanY = (depth - 1) * STACK_STEP_Y;
  const layerHeight = frontHeight ?? `calc(100% - ${spanY}px)`;
  return (
    <div
      ref={shuffle}
      aria-label={`${count} items in sequence`}
      {...stylex.props(s.stack)}
      style={
        frontHeight === undefined
          ? { paddingRight: spanX, paddingBottom: spanY }
          : { height: frontHeight + spanY }
      }
    >
      {stackSlots(count, index).map((slot) => {
        const inFlow =
          frontHeight === undefined && slot.slot === 0 && !slot.tail;
        const style: React.CSSProperties = inFlow
          ? { position: "relative", zIndex: depth }
          : {
              position: "absolute",
              left: slot.slot * STACK_STEP_X,
              top: slot.slot * STACK_STEP_Y,
              width: `calc(100% - ${spanX}px)`,
              height: layerHeight,
              zIndex: slot.tail ? 0 : depth - slot.slot,
              ...(slot.tail ? { opacity: 0, pointerEvents: "none" } : {}),
            };
        return (
          // Keyed by sequence position, which a page never changes: a sequence
          // may hold one artifact twice, and a layer keeps its element as it
          // moves from slot to slot, which is what lets it animate there.
          <React.Fragment key={slot.item}>
            {renderLayer(slot, {
              "data-stack-item": slot.item,
              "aria-hidden": slot.tail ? true : undefined,
              style,
            })}
          </React.Fragment>
        );
      })}
      {overlay ? (
        <div
          {...stylex.props(s.overlay)}
          style={{
            width: `calc(100% - ${spanX}px)`,
            height: layerHeight,
            zIndex: depth + 2,
          }}
        >
          {overlay}
        </div>
      ) : null}
    </div>
  );
}

/**
 * Props for a plain layer behind a body that only the front item draws. Spread
 * on the same element type as the front layer: a layer that changed element
 * type between pages would be remounted instead of moved, and lose its way.
 */
export function stackPlateProps(tail: boolean) {
  return {
    "aria-hidden": true as const,
    "data-artifact-shadow-scope": tail ? undefined : "sequence-item",
    ...stylex.props(s.layer),
  };
}
