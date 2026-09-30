// @vitest-environment jsdom

import * as React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { canvasMenuTarget, wantsNativeMenu } from "./canvas-menu-target";
import type { CanvasMenuRequest } from "./canvas-menu-target";
import { useCanvasMenuTrigger } from "./useCanvasMenuTrigger";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

/** A canvas as React Flow draws it: pane, a node with a field, an edge, a panel. */
function canvasMarkup(): string {
  return `
    <div class="react-flow">
      <div class="react-flow__pane">
        <div class="react-flow__viewport">
          <div class="react-flow__node" data-id="node-1">
            <header><span class="title">Split text</span></header>
            <div class="react-flow__handle" data-id="flow-node-1-text-target"></div>
            <input aria-label="Separator" />
          </div>
          <svg><g class="react-flow__edge" data-id="edge-1"><path class="edge-path" /></g></svg>
          <div class="react-flow__nodesselection-rect"></div>
          <div class="react-flow__edgelabel-renderer"><button class="chip">Map</button></div>
        </div>
      </div>
      <div class="react-flow__panel"><button class="zoom">+</button></div>
    </div>
    <div class="outside"></div>`;
}

const roots: ReturnType<typeof createRoot>[] = [];

afterEach(() => {
  React.act(() => {
    for (const root of roots.splice(0)) root.unmount();
  });
  document.body.replaceChildren();
});

function el(selector: string): Element {
  const found = document.querySelector(selector);
  if (!found) throw new Error(`No ${selector}`);
  return found;
}

describe("canvasMenuTarget", () => {
  it("names what a right-click landed on", () => {
    document.body.innerHTML = canvasMarkup();

    expect(canvasMenuTarget(el(".title"))).toEqual({
      kind: "node",
      nodeId: "node-1",
    });
    // A port handle carries its own data-id; the node still answers.
    expect(canvasMenuTarget(el(".react-flow__handle"))).toEqual({
      kind: "node",
      nodeId: "node-1",
    });
    expect(canvasMenuTarget(el(".edge-path"))).toEqual({
      kind: "edge",
      edgeId: "edge-1",
    });
    expect(canvasMenuTarget(el(".react-flow__nodesselection-rect"))).toEqual({
      kind: "selection",
    });
    expect(canvasMenuTarget(el(".react-flow__viewport"))).toEqual({
      kind: "pane",
    });
    expect(canvasMenuTarget(el(".chip"))).toBeNull();
    expect(canvasMenuTarget(el(".zoom"))).toBeNull();
    expect(canvasMenuTarget(el(".outside"))).toBeNull();
  });

  it("leaves text fields to the browser's own menu", () => {
    document.body.innerHTML = canvasMarkup();

    expect(wantsNativeMenu(el("input"))).toBe(true);
    expect(wantsNativeMenu(el(".title"))).toBe(false);
  });
});

function renderTrigger(): {
  onOpen: ReturnType<typeof vi.fn>;
  section: HTMLElement;
} {
  const onOpen = vi.fn<(request: CanvasMenuRequest) => void>();
  function Canvas() {
    const trigger = useCanvasMenuTrigger(onOpen);
    return (
      <section
        data-testid="canvas"
        onPointerDownCapture={trigger.onPointerDownCapture}
        onContextMenu={trigger.onContextMenu}
        onKeyDown={trigger.onKeyDown}
        dangerouslySetInnerHTML={{ __html: canvasMarkup() }}
      />
    );
  }
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  roots.push(root);
  React.act(() => root.render(<Canvas />));
  return { onOpen, section: el('[data-testid="canvas"]') as HTMLElement };
}

function pointer(
  target: Element,
  type: string,
  init: { x: number; y: number; button?: number; pointerType?: string },
): void {
  const event = new MouseEvent(type, {
    bubbles: true,
    cancelable: true,
    clientX: init.x,
    clientY: init.y,
    button: init.button ?? 2,
  });
  Object.defineProperties(event, {
    pointerType: { value: init.pointerType ?? "mouse" },
    pointerId: { value: 1 },
    isPrimary: { value: true },
  });
  React.act(() => {
    target.dispatchEvent(event);
  });
}

describe("useCanvasMenuTrigger", () => {
  it("opens on a right click and leaves a right drag to panning", () => {
    const { onOpen } = renderTrigger();

    pointer(el(".react-flow__viewport"), "pointerdown", { x: 100, y: 80 });
    pointer(document.body, "pointerup", { x: 102, y: 81 });
    expect(onOpen).toHaveBeenCalledWith({
      point: { x: 102, y: 81 },
      target: { kind: "pane" },
    });

    onOpen.mockClear();
    pointer(el(".title"), "pointerdown", { x: 100, y: 80 });
    pointer(document.body, "pointerup", { x: 160, y: 120 });
    expect(onOpen).not.toHaveBeenCalled();
  });

  it("keeps the browser's menu in text fields and on chrome over the canvas", () => {
    const { onOpen } = renderTrigger();

    pointer(el("input"), "pointerdown", { x: 10, y: 10 });
    pointer(document.body, "pointerup", { x: 10, y: 10 });
    const native = new MouseEvent("contextmenu", {
      bubbles: true,
      cancelable: true,
    });
    React.act(() => {
      el("input").dispatchEvent(native);
    });

    expect(onOpen).not.toHaveBeenCalled();
    expect(native.defaultPrevented).toBe(false);

    const onCanvas = new MouseEvent("contextmenu", {
      bubbles: true,
      cancelable: true,
    });
    React.act(() => {
      el(".title").dispatchEvent(onCanvas);
    });
    expect(onCanvas.defaultPrevented).toBe(true);
  });

  it("answers a Mac Ctrl-click and the keyboard's menu keys", () => {
    const { onOpen } = renderTrigger();

    const ctrlClick = new MouseEvent("contextmenu", {
      bubbles: true,
      cancelable: true,
      button: 0,
      ctrlKey: true,
      clientX: 40,
      clientY: 50,
    });
    React.act(() => {
      el(".title").dispatchEvent(ctrlClick);
    });
    expect(onOpen).toHaveBeenLastCalledWith({
      point: { x: 40, y: 50 },
      target: { kind: "node", nodeId: "node-1" },
    });

    const node = el(".react-flow__node") as HTMLElement;
    node.tabIndex = 0;
    node.focus();
    React.act(() => {
      node.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "F10",
          shiftKey: true,
          bubbles: true,
          cancelable: true,
        }),
      );
    });
    expect(onOpen).toHaveBeenLastCalledWith(
      expect.objectContaining({ target: { kind: "node", nodeId: "node-1" } }),
    );
  });

  it("opens on a held finger's lift, never on a tap or a pan", () => {
    vi.useFakeTimers();
    try {
      const { onOpen } = renderTrigger();
      const pane = el(".react-flow__viewport");
      const touch = { pointerType: "touch", button: 0 };

      // A tap.
      pointer(pane, "pointerdown", { x: 50, y: 50, ...touch });
      pointer(document.body, "pointerup", { x: 50, y: 50, ...touch });
      React.act(() => void vi.advanceTimersByTime(600));
      expect(onOpen).not.toHaveBeenCalled();

      // A finger that moves while held is panning.
      pointer(pane, "pointerdown", { x: 50, y: 50, ...touch });
      pointer(document.body, "pointermove", { x: 90, y: 50, ...touch });
      React.act(() => void vi.advanceTimersByTime(600));
      pointer(document.body, "pointerup", { x: 90, y: 50, ...touch });
      expect(onOpen).not.toHaveBeenCalled();

      // A finger held still, then lifted.
      pointer(pane, "pointerdown", { x: 50, y: 50, ...touch });
      React.act(() => void vi.advanceTimersByTime(600));
      expect(onOpen).not.toHaveBeenCalled();
      pointer(document.body, "pointerup", { x: 51, y: 50, ...touch });
      expect(onOpen).toHaveBeenCalledWith({
        point: { x: 50, y: 50 },
        target: { kind: "pane" },
      });

      // The tap the lift stands for does not reach the canvas.
      const tap = new MouseEvent("mousedown", {
        bubbles: true,
        cancelable: true,
      });
      React.act(() => {
        pane.dispatchEvent(tap);
      });
      expect(tap.defaultPrevented).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });
});
