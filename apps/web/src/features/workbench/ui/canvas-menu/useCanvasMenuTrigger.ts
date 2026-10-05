"use client";

import * as React from "react";

import {
  canvasMenuTarget,
  wantsNativeMenu,
  type CanvasMenuRequest,
} from "./canvas-menu-target";

/** A right button that moves further than this was a pan, not a click. */
const CLICK_SLOP_PX = 5;
/** How long a finger rests before it asks for the menu. */
const LONG_PRESS_MS = 500;
const LONG_PRESS_SLOP_PX = 10;

type Point = { x: number; y: number };

function distance(from: Point, to: Point): number {
  return Math.hypot(to.x - from.x, to.y - from.y);
}

/**
 * After a touch ends the browser still sends the mouse events a tap stands
 * for: mousedown, mouseup, click. The menu that opens on the lift would read
 * that mousedown as a press outside it and close, so the lift eats them. The
 * menu listens on the document too, hence stopping the listeners beside this
 * one as well.
 */
function swallowTapMouseEvents(): void {
  const types = ["mousedown", "mouseup", "click"] as const;
  const swallow = (event: Event) => {
    event.preventDefault();
    event.stopImmediatePropagation();
  };
  for (const type of types) {
    document.addEventListener(type, swallow, { capture: true, once: true });
  }
  window.setTimeout(() => {
    for (const type of types) {
      document.removeEventListener(type, swallow, true);
    }
  }, LONG_PRESS_MS);
}

/**
 * Opens the canvas menu without taking the right button away from panning.
 *
 * The canvas pans on a right-drag, and the browser's `contextmenu` event comes
 * too early on macOS (at press) to tell a click from a drag. So the menu opens
 * when the right button is released close to where it went down. A Mac
 * Ctrl-click, Shift+F10 or the Menu key, and a long press on touch open it too.
 * Text fields keep the browser's own menu.
 */
export function useCanvasMenuTrigger(
  onOpen: (request: CanvasMenuRequest) => void,
): {
  onPointerDownCapture: (event: React.PointerEvent<HTMLElement>) => void;
  onContextMenu: (event: React.MouseEvent<HTMLElement>) => void;
  onKeyDown: (event: React.KeyboardEvent<HTMLElement>) => void;
} {
  const onOpenRef = React.useRef(onOpen);
  React.useLayoutEffect(() => {
    onOpenRef.current = onOpen;
  });
  const pending = React.useRef<(() => void) | null>(null);

  React.useEffect(() => () => pending.current?.(), []);

  function watch(listeners: [string, EventListener][]): () => void {
    for (const [type, listener] of listeners) {
      document.addEventListener(type, listener, true);
    }
    const stop = () => {
      for (const [type, listener] of listeners) {
        document.removeEventListener(type, listener, true);
      }
      if (pending.current === stop) pending.current = null;
    };
    pending.current?.();
    pending.current = stop;
    return stop;
  }

  function onRightPress(
    event: React.PointerEvent<HTMLElement>,
    target: Element,
  ) {
    const menuTarget = canvasMenuTarget(target);
    if (!menuTarget) return;
    const start = { x: event.clientX, y: event.clientY };
    const stop = watch([
      [
        "pointerup",
        ((up: PointerEvent) => {
          if (up.button !== 2) return;
          stop();
          const end = { x: up.clientX, y: up.clientY };
          if (distance(start, end) > CLICK_SLOP_PX) return;
          onOpenRef.current({ point: end, target: menuTarget });
        }) as EventListener,
      ],
    ]);
  }

  /**
   * A finger held still arms the menu; lifting it opens the menu. Opening on
   * the lift, not under the finger, keeps the lift from reading as a press
   * outside the menu that closes it again.
   */
  function onTouchPress(
    event: React.PointerEvent<HTMLElement>,
    target: Element,
  ) {
    const menuTarget = canvasMenuTarget(target);
    if (!menuTarget) return;
    const start = { x: event.clientX, y: event.clientY };
    const pointerId = event.pointerId;
    let armed = false;
    const timer = window.setTimeout(() => {
      armed = true;
      navigator.vibrate?.(10);
    }, LONG_PRESS_MS);
    // Every way a press ends also ends its timer.
    const end = () => {
      window.clearTimeout(timer);
      stopWatching();
      if (pending.current === end) pending.current = null;
    };
    const stopWatching = watch([
      [
        "pointermove",
        ((move: PointerEvent) => {
          if (move.pointerId !== pointerId) return;
          const moved = { x: move.clientX, y: move.clientY };
          if (distance(start, moved) > LONG_PRESS_SLOP_PX) end();
        }) as EventListener,
      ],
      [
        "pointerup",
        ((up: PointerEvent) => {
          if (up.pointerId !== pointerId) return;
          const open = armed;
          end();
          if (!open) return;
          // The same lift must not also tap the canvas under the menu.
          swallowTapMouseEvents();
          onOpenRef.current({ point: start, target: menuTarget });
        }) as EventListener,
      ],
      ["pointercancel", end],
      // A second finger is a pinch.
      [
        "pointerdown",
        ((down: PointerEvent) => {
          if (down.pointerId !== pointerId) end();
        }) as EventListener,
      ],
    ]);
    pending.current = end;
  }

  return {
    onPointerDownCapture(event) {
      if (!(event.target instanceof Element) || wantsNativeMenu(event.target)) {
        return;
      }
      if (event.pointerType === "mouse" && event.button === 2) {
        onRightPress(event, event.target);
      } else if (event.pointerType === "touch" && event.isPrimary) {
        onTouchPress(event, event.target);
      }
    },
    onContextMenu(event) {
      if (!(event.target instanceof Element) || wantsNativeMenu(event.target)) {
        return;
      }
      if (!canvasMenuTarget(event.target)) return;
      event.preventDefault();
      // A Mac Ctrl-click never presses the right button; answer the event.
      if (event.button === 0 && event.ctrlKey) {
        const target = canvasMenuTarget(event.target);
        if (target) {
          onOpenRef.current({
            point: { x: event.clientX, y: event.clientY },
            target,
          });
        }
      }
    },
    onKeyDown(event) {
      const asked =
        event.key === "ContextMenu" || (event.shiftKey && event.key === "F10");
      if (!asked || !(event.target instanceof Element)) return;
      if (wantsNativeMenu(event.target)) return;
      const focused = event.target;
      const node = focused.closest(".react-flow__node");
      const box = (node ?? event.currentTarget).getBoundingClientRect();
      const target = node ? canvasMenuTarget(node) : { kind: "pane" as const };
      if (!target) return;
      event.preventDefault();
      onOpenRef.current({
        point: node
          ? { x: box.left + 24, y: box.top + 24 }
          : { x: box.left + box.width / 2, y: box.top + box.height / 2 },
        target,
      });
    },
  };
}
