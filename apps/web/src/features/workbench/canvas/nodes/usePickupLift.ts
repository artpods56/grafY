import * as React from "react";

/**
 * Pickup lift state machine (spike option C): rest → active (−2px) →
 * dragged (−8px). Selection raises a node to the active tier; a real
 * React Flow drag — or holding the press for a beat — promotes it to the
 * dragged tier. Hold-lift is group-aware: holding any member of the current
 * selection lifts the whole selection, because any subsequent move would
 * drag the group. While the spring lift runs, handle bounds are remeasured on
 * every frame that carries the card further than {@link LIFT_TRACK_TOLERANCE_PX}
 * so connected edges glide with the handles instead of jumping at settle, and
 * the frames the easing spends creeping cost nothing; a real drag instead snaps
 * the lift and remeasures immediately so bounds are fresh before the drag loop
 * begins.
 */

export type PickupTier = "rest" | "active" | "dragged";

const HOLD_TO_LIFT_MS = 150;
const HOLD_MOVE_CANCEL_PX = 3;
const SETTLE_FALLBACK_MS = 260;

/**
 * Client pixels the lifted card may travel, past the last point React Flow was
 * told to measure, before another measurement is worth its price.
 *
 * The lift is a CSS transform on the card, and React Flow only learns where the
 * handles went when it is asked to look again. One look is not cheap: it re-measures
 * this node's handles, walks the absolute position of every node, and notifies the
 * whole store — 6.4 ms of main thread on a 17-node, 11-edge graph at zoom 1, against
 * a 0.3 ms idle frame. The lift carries a connected port 4 px when a card is selected
 * and 10 px when it is held, about a dozen painted frames per tier, and the easing
 * spends most of them creeping: of the 34 frames in which a port moves across
 * select → hold → release, only 14 move it half a pixel or more. So the animation is
 * followed to within this tolerance and the frames in between are free, which turned
 * those 35 animation frames into 18 measurements, and the wires an animation used to
 * redraw 13 times per tier into 4. The resting geometry is always measured, both at
 * settle and at the fallback stop, so a gesture never leaves a stale port behind for
 * the next wire to snap to.
 */
const LIFT_TRACK_TOLERANCE_PX = 0.5;

/** Where the lifted card stands on screen right now, or null once it is gone. */
function liftedTop(element: HTMLElement | null): number | null {
  if (!element) return null;
  return element.getBoundingClientRect().top;
}

/**
 * Shared hold-to-lift signal. Holding any node that is part of the current
 * selection lifts the whole selection (a subsequent move would drag the
 * group), so the held id is module-level state observed by every node via
 * `useSyncExternalStore` — no extra dependency needed.
 */
let heldNodeId: string | null = null;
const heldListeners = new Set<() => void>();
function subscribeHeld(listener: () => void) {
  heldListeners.add(listener);
  return () => {
    heldListeners.delete(listener);
  };
}
function getHeldNodeId() {
  return heldNodeId;
}
function setHeldNodeId(next: string | null) {
  if (heldNodeId === next) return;
  heldNodeId = next;
  heldListeners.forEach((listener) => listener());
}
function useHeldNodeId() {
  // The held node is set by a pointer gesture, so the server value is always
  // null. Without this the node card throws while server rendering.
  return React.useSyncExternalStore(subscribeHeld, getHeldNodeId, () => null);
}

interface PickupLiftOptions {
  id: string;
  selected: boolean | undefined;
  dragging: boolean | undefined;
  updateNodeInternals: (id: string) => void;
}

export function usePickupLift({
  id,
  selected,
  dragging,
  updateNodeInternals,
}: PickupLiftOptions) {
  const [pressing, setPressing] = React.useState(false);
  const holdTimer = React.useRef<number | null>(null);
  const holdOrigin = React.useRef<{ x: number; y: number } | null>(null);
  const liftRef = React.useRef<HTMLDivElement | null>(null);
  const heldNodeId = useHeldNodeId();
  const selectedRef = React.useRef(Boolean(selected));
  React.useEffect(() => {
    selectedRef.current = Boolean(selected);
  }, [selected]);

  const clearHold = React.useCallback(() => {
    if (holdTimer.current !== null) {
      window.clearTimeout(holdTimer.current);
      holdTimer.current = null;
    }
    holdOrigin.current = null;
  }, []);

  React.useEffect(() => () => clearHold(), [clearHold]);

  // A real drag supersedes the hold gesture: cancel the pending promotion.
  // (Held state itself is cleared by the window pointerup/pointercancel
  // listeners, so no setState is needed here.)
  React.useEffect(() => {
    if (dragging) {
      clearHold();
      if (getHeldNodeId() === id) setHeldNodeId(null);
    }
  }, [dragging, clearHold, id]);

  // Leaving the canvas unmounts a node mid-press; do not strand the group lift.
  React.useEffect(
    () => () => {
      if (getHeldNodeId() === id) setHeldNodeId(null);
    },
    [id],
  );

  // Release anywhere ends the hold (the pointer can leave the node mid-press).
  React.useEffect(() => {
    if (!pressing) return;
    const release = () => {
      setPressing(false);
      clearHold();
      if (getHeldNodeId() === id) setHeldNodeId(null);
    };
    window.addEventListener("pointerup", release);
    window.addEventListener("pointercancel", release);
    return () => {
      window.removeEventListener("pointerup", release);
      window.removeEventListener("pointercancel", release);
    };
  }, [pressing, clearHold, id]);

  const onPointerDown = React.useCallback(
    (event: React.PointerEvent<HTMLElement>) => {
      if (event.button !== 0) return;
      if ((event.target as HTMLElement).closest(".nodrag")) return;
      clearHold();
      setPressing(true);
      holdOrigin.current = { x: event.clientX, y: event.clientY };
      holdTimer.current = window.setTimeout(() => {
        holdTimer.current = null;
        holdOrigin.current = null;
        // Only a held member of the current selection lifts the group; a
        // press that does not select (e.g. on a nodrag surface race) must not.
        if (selectedRef.current) setHeldNodeId(id);
      }, HOLD_TO_LIFT_MS);
    },
    [clearHold, id],
  );

  const onPointerMove = React.useCallback(
    (event: React.PointerEvent<HTMLElement>) => {
      const origin = holdOrigin.current;
      if (!origin) return;
      if (
        Math.hypot(event.clientX - origin.x, event.clientY - origin.y) >
        HOLD_MOVE_CANCEL_PX
      ) {
        clearHold();
      }
    },
    [clearHold],
  );

  const holdHandlers = React.useMemo(
    () => ({ onPointerDown, onPointerMove }),
    [onPointerDown, onPointerMove],
  );

  const heldActive = heldNodeId !== null;
  const draggedTier = Boolean(dragging) || (Boolean(selected) && heldActive);
  const pickedUp = Boolean(selected) || draggedTier;
  const tier: PickupTier = draggedTier
    ? "dragged"
    : pickedUp
      ? "active"
      : "rest";

  const prefersReducedMotion = React.useMemo(
    () =>
      typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    [],
  );

  const prevTier = React.useRef<PickupTier>(tier);
  React.useLayoutEffect(() => {
    const previous = prevTier.current;
    prevTier.current = tier;
    if (previous === tier) return;
    const element = liftRef.current;
    if (!element || prefersReducedMotion) {
      updateNodeInternals(id);
      return;
    }
    if (tier === "dragged" && dragging) {
      // A real drag needs fresh handle bounds right now: snap the lift past
      // any running spring, measure, then hand the transition back.
      element.style.transition = "none";
      void element.offsetWidth;
      updateNodeInternals(id);
      const frame = window.requestAnimationFrame(() => {
        element.style.transition = "";
      });
      return () => window.cancelAnimationFrame(frame);
    }
    // Track the lift for as long as it travels, so connected edges glide with the
    // handles instead of jumping when the animation settles. React Flow cannot see
    // the transform by itself: it stores handle bounds relative to the node element,
    // and the node element does not move — only the card inside it does. So the
    // bounds only follow if a measurement is asked for, and asking is what costs
    // (see LIFT_TRACK_TOLERANCE_PX). The measurement itself lands one frame later,
    // because that is how `useUpdateNodeInternals` schedules it, which was already
    // true of every frame here.
    const lift = element;
    let frame = 0;
    let fallback = 0;
    let stopped = false;
    // Where the card stood the last time React Flow was told to measure it. The
    // previous tier's settle left the store's bounds there, so the animation starts
    // from a known-good position and only its travel needs following.
    let sweptTop = liftedTop(lift) ?? 0;
    function stop() {
      if (stopped) return;
      stopped = true;
      window.cancelAnimationFrame(frame);
      window.clearTimeout(fallback);
      lift.removeEventListener("transitionend", onSettle);
      sweptTop = liftedTop(lift) ?? sweptTop;
      updateNodeInternals(id);
    }
    function onSettle(event: TransitionEvent) {
      if (event.target === lift && event.propertyName === "transform") {
        stop();
      }
    }
    function loop() {
      if (stopped) return;
      const top = liftedTop(lift);
      if (top !== null && Math.abs(top - sweptTop) >= LIFT_TRACK_TOLERANCE_PX) {
        sweptTop = top;
        updateNodeInternals(id);
      }
      frame = window.requestAnimationFrame(loop);
    }
    lift.addEventListener("transitionend", onSettle);
    frame = window.requestAnimationFrame(loop);
    fallback = window.setTimeout(stop, SETTLE_FALLBACK_MS);
    return () => {
      stopped = true;
      window.cancelAnimationFrame(frame);
      window.clearTimeout(fallback);
      lift.removeEventListener("transitionend", onSettle);
    };
  }, [tier, dragging, id, prefersReducedMotion, updateNodeInternals]);

  return { tier, pickedUp, draggedTier, liftRef, holdHandlers };
}

/**
 * Keep React Flow's handle bounds current while ports slide by CSS alone:
 * whenever `motion` changes, remeasure next frame and again once it settles.
 * A port that carries an edge never slides (it stays out), so no edge follows
 * a moving port and there is nothing to track frame by frame; the settled
 * measurement is what connection snapping reads.
 */
export function useFollowHandleMotion({
  id,
  motion,
  durationMs,
  updateNodeInternals,
}: {
  id: string;
  motion: string;
  durationMs: number;
  updateNodeInternals: (id: string) => void;
}) {
  const previous = React.useRef(motion);
  React.useLayoutEffect(() => {
    if (previous.current === motion) return;
    previous.current = motion;
    const frame = window.requestAnimationFrame(() => updateNodeInternals(id));
    const settled = window.setTimeout(
      () => updateNodeInternals(id),
      durationMs + 20,
    );
    return () => {
      window.cancelAnimationFrame(frame);
      window.clearTimeout(settled);
    };
  }, [durationMs, id, motion, updateNodeInternals]);
}
