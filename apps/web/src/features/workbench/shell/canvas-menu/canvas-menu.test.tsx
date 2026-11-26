// @vitest-environment jsdom

import * as React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { canvasMenuTarget, wantsNativeMenu } from "./canvas-menu-target";
import type { CanvasMenuRequest } from "./canvas-menu-target";
import {
  CanvasContextMenu,
  type CanvasMenuActions,
  type CanvasMenuSelection,
} from "./CanvasContextMenu";
import { NodeMenuRegistry } from "../node-menu-registry";
import { useCanvasMenuTrigger } from "./useCanvasMenuTrigger";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

/** A CellCanvas pane with a card, a pipe and canvas chrome. */
function canvasMarkup(): string {
  return `
    <div data-cell-canvas="true">
      <div class="viewport">
        <div data-cell-card="true" data-card-id="node-1">
          <header><span class="title">Split text</span></header>
          <div class="port" data-cell-port="text-target"></div>
          <input aria-label="Separator" />
        </div>
        <svg><path data-pipe-hit="edge-1" class="edge-path" /></svg>
        <button data-edge-selector-pill="edge-1" class="chip">Map</button>
      </div>
      <div data-cell-canvas-chrome="true"><button class="zoom">+</button></div>
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
    // A port belongs to its card.
    expect(canvasMenuTarget(el(".port"))).toEqual({
      kind: "node",
      nodeId: "node-1",
    });
    expect(canvasMenuTarget(el(".edge-path"))).toEqual({
      kind: "edge",
      edgeId: "edge-1",
    });
    expect(canvasMenuTarget(el(".viewport"))).toEqual({
      kind: "pane",
    });
    expect(canvasMenuTarget(el(".chip"))).toEqual({
      kind: "edge",
      edgeId: "edge-1",
    });
    expect(canvasMenuTarget(el(".zoom"))).toBeNull();
    expect(canvasMenuTarget(el(".outside"))).toBeNull();
  });

  it("identifies cards, pills, docked joins, pane, and chrome on the cell canvas", () => {
    document.body.innerHTML = `
      <div data-cell-canvas="true">
        <div data-cell-card="true" data-card-id="card-1"><span class="card-title">OCR</span></div>
        <div data-edge-selector-pill="edge-1"><span class="pill-text">text</span></div>
        <button data-docked-join="edge-2"><span class="join-line"></span></button>
        <svg><path data-pipe-hit="edge-3" /></svg>
        <div data-cell-canvas-chrome="true"><button class="toolbar-btn">Run</button></div>
        <div class="cell-empty"></div>
      </div>`;

    expect(canvasMenuTarget(el(".card-title"))).toEqual({
      kind: "node",
      nodeId: "card-1",
    });
    expect(canvasMenuTarget(el(".pill-text"))).toEqual({
      kind: "edge",
      edgeId: "edge-1",
    });
    expect(canvasMenuTarget(el(".join-line"))).toEqual({
      kind: "edge",
      edgeId: "edge-2",
    });
    expect(canvasMenuTarget(el('[data-pipe-hit="edge-3"]'))).toEqual({
      kind: "edge",
      edgeId: "edge-3",
    });
    expect(canvasMenuTarget(el(".cell-empty"))).toEqual({ kind: "pane" });
    expect(canvasMenuTarget(el(".toolbar-btn"))).toBeNull();
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

    pointer(el(".viewport"), "pointerdown", { x: 100, y: 80 });
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

    const node = el('[data-cell-card="true"]') as HTMLElement;
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
      const pane = el(".viewport");
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
      React.act(() => void vi.advanceTimersByTime(600));
    } finally {
      vi.useRealTimers();
    }
  });
});

function stubActions(): CanvasMenuActions {
  return {
    searchNodes: vi.fn(),
    addNodeHere: vi.fn(),
    addAnnotationHere: vi.fn(),
    selectAll: vi.fn(),
    cleanUpCanvas: vi.fn(),
    fitView: vi.fn(),
    runSelection: vi.fn(),
    collect: vi.fn(),
    tidy: vi.fn(),
    duplicate: vi.fn(),
    remove: vi.fn(),
    fitSelection: vi.fn(),
    deleteEdge: vi.fn(),
  };
}

describe("CanvasContextMenu cleanup actions", () => {
  it("offers Clean up canvas on the pane menu and invokes cleanUpCanvas", async () => {
    const actions = stubActions();
    const selection: CanvasMenuSelection = {
      count: 0,
      workflowCount: 0,
      canRun: false,
      canDuplicate: false,
      canDelete: false,
      collect: null,
      canTidy: false,
      canCleanUpCanvas: true,
    };
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    roots.push(root);
    await React.act(async () => {
      root.render(
        <CanvasContextMenu
          request={{ point: { x: 120, y: 120 }, target: { kind: "pane" } }}
          registry={null}
          activeGraphId="g1"
          canEdit={true}
          selection={selection}
          nodeMenus={new NodeMenuRegistry()}
          actions={actions}
          onClose={() => undefined}
        />,
      );
    });

    const items = Array.from(document.querySelectorAll('[role="menuitem"]'));
    const cleanUp = items.find((item) =>
      item.textContent?.includes("Clean up canvas"),
    ) as HTMLElement | undefined;
    expect(cleanUp).toBeDefined();
    expect(cleanUp?.getAttribute("aria-disabled")).not.toBe("true");
    await React.act(async () => {
      cleanUp?.click();
    });
    expect(actions.cleanUpCanvas).toHaveBeenCalledTimes(1);
  });

  it("offers Tidy up on a mixed selection of workflow and artifact cards", async () => {
    const actions = stubActions();
    const selection: CanvasMenuSelection = {
      count: 3,
      workflowCount: 2,
      canRun: true,
      canDuplicate: true,
      canDelete: true,
      collect: null,
      canTidy: true,
      canCleanUpCanvas: true,
    };
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    roots.push(root);
    await React.act(async () => {
      root.render(
        <CanvasContextMenu
          request={{ point: { x: 160, y: 160 }, target: { kind: "selection" } }}
          registry={null}
          activeGraphId="g1"
          canEdit={true}
          selection={selection}
          nodeMenus={new NodeMenuRegistry()}
          actions={actions}
          onClose={() => undefined}
        />,
      );
    });

    const items = Array.from(document.querySelectorAll('[role="menuitem"]'));
    const tidy = items.find((item) => item.textContent?.includes("Tidy up")) as
      HTMLElement | undefined;
    expect(tidy).toBeDefined();
    await React.act(async () => {
      tidy?.click();
    });
    expect(actions.tidy).toHaveBeenCalledTimes(1);
  });
});
