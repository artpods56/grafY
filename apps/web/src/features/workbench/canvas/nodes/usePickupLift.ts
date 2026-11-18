import * as React from "react";

/**
 * Pickup lift state machine (spike option C): rest → active (−2px) →
 * dragged (−8px). Selection raises a node to the active tier; a real
 * React Flow drag — or holding the press for a beat — promotes it to the
 * dragged tier. Hold-lift is group-aware: holding any member of the current
 * selection lifts the whole selection, because any subsequent move would
 * drag the group.
 *
 * A card lifted by a CSS transform takes its ports with it, and React Flow only
 * learns where they went when it is asked to look again; asking is expensive, so it
 * is asked once per tier, when the card stops travelling. Connected wires therefore
 * jump the last few pixels at settle instead of gliding along with the spring.
 */

export type PickupTier = "rest" | "active" | "dragged";

const HOLD_TO_LIFT_MS = 150;
const HOLD_MOVE_CANCEL_PX = 3;

/**
 * How long to wait for a lift that never announces it has stopped: an interrupted
 * style, a hidden tab, a transition the browser skipped.
 *
 * This wait replaces a sweep that watched every painted frame. One measurement is
 * not cheap: it re-measures this node's handles, walks the absolute position of every
 * node, and notifies the whole store — 6.4 ms of main thread on a 17-node, 11-edge
 * graph at zoom 1, against a 0.3 ms idle frame. Following a lift frame by frame, even
 * only on the frames that carried a port half a pixel, cost about eighteen of those
 * per pick-up gesture: ~115 ms of main thread to keep a 4 px rise honest. One look
 * per tier costs 6.4 ms, and the resting geometry is still always measured, here or at
 * settle, so a gesture leaves no stale port behind for the next wire to snap to.
 */
const SETTLE_FALLBACK_MS = 260;

/**
 * Shared hold-to-lift signal. Holding any node that is part of the current
 * selection lifts the whole selection (a subsequent move would drag the
 * group), so the held id is module-level state rather than a prop threaded
 * through every card.
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

/**
 * Whether a hold lifts this card.
 *
 * A hold only ever comes from a selected card, and only a selected card can be
 * lifted by it, so a card outside the selection reads `null` whatever the store
 * holds. Reading the held id through the snapshot rather than the raw store value is
 * what decides who re-renders: notifying every mounted card and letting each one
 * decide re-rendered all of them, twice, for a gesture on one of them.
 */
function useHeldLift(selected: boolean | undefined): boolean {
  return (
    React.useSyncExternalStore(
      subscribeHeld,
      // A hold is set by a pointer gesture, so the server value is always null.
      // Without this the node card throws while server rendering.
      () => (selected ? heldNodeId : null),
      () => null,
    ) !== null
  );
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
  const heldActive = useHeldLift(selected);
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
    // One look, taken when the card stops travelling. The lift is a transform on
    // the card, so React Flow's stored bounds cannot follow it on their own; the
    // frames an easing spends creeping are simply not looked at, and the settle is
    // what the store ends up holding.
    const lift = element;
    let stopped = false;
    let fallback = 0;
    function stop() {
      if (stopped) return;
      stopped = true;
      window.clearTimeout(fallback);
      lift.removeEventListener("transitionend", onSettle);
      updateNodeInternals(id);
    }
    function onSettle(event: TransitionEvent) {
      if (event.target === lift && event.propertyName === "transform") {
        stop();
      }
    }
    lift.addEventListener("transitionend", onSettle);
    fallback = window.setTimeout(stop, SETTLE_FALLBACK_MS);
    return () => {
      stopped = true;
      window.clearTimeout(fallback);
      lift.removeEventListener("transitionend", onSettle);
    };
  }, [id, prefersReducedMotion, tier, updateNodeInternals]);

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
