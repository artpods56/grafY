// @vitest-environment jsdom

import * as React from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles,>(styles: Styles) => styles,
  props: () => ({}),
}));

vi.mock("@xyflow/react", () => ({
  useViewport: () => ({ zoom: 1, x: 0, y: 0 }),
}));

vi.mock("../canvas-grid-settings", () => ({
  useOptionalCanvasGridSettings: () => ({
    settings: {
      enabled: true,
      showBackground: true,
      snapPosition: true,
      snapSize: true,
      snapWhileDragging: false,
      snapWhileResizing: true,
      allowWorkflowCornerResize: false,
      cellSize: 50,
    },
    bypassSnap: false,
  }),
}));

import { TextareaBodyResizeHandle } from "./TextareaBodyResizeHandle";

function pointerEvent(
  type: string,
  init: {
    pointerId: number;
    button?: number;
    clientX: number;
    clientY: number;
  },
) {
  const event = new Event(type, {
    bubbles: true,
    cancelable: true,
  }) as Event & {
    pointerId: number;
    button: number;
    clientX: number;
    clientY: number;
    altKey: boolean;
  };
  event.pointerId = init.pointerId;
  event.button = init.button ?? 0;
  event.clientX = init.clientX;
  event.clientY = init.clientY;
  event.altKey = false;
  return event;
}

describe("TextareaBodyResizeHandle", () => {
  it("commits snapped width and bodyHeight after a diagonal drag", () => {
    Object.assign(HTMLElement.prototype, {
      setPointerCapture: () => undefined,
      releasePointerCapture: () => undefined,
      hasPointerCapture: () => false,
    });

    const onDraft = vi.fn();
    const onCommit = vi.fn();
    const container = document.createElement("div");
    const root = createRoot(container);
    React.act(() => {
      root.render(
        <TextareaBodyResizeHandle
          layout={{ width: 300, bodyHeight: 100 }}
          ariaLabel="Resize SQL field"
          onDraft={onDraft}
          onCommit={onCommit}
        />,
      );
    });

    const handle = container.querySelector("button");
    expect(handle).not.toBeNull();
    React.act(() => {
      handle?.dispatchEvent(
        pointerEvent("pointerdown", {
          pointerId: 1,
          button: 0,
          clientX: 100,
          clientY: 100,
        }),
      );
      handle?.dispatchEvent(
        pointerEvent("pointermove", {
          pointerId: 1,
          clientX: 160,
          clientY: 150,
        }),
      );
      handle?.dispatchEvent(
        pointerEvent("pointerup", {
          pointerId: 1,
          clientX: 160,
          clientY: 150,
        }),
      );
    });

    expect(onDraft).toHaveBeenCalled();
    expect(onCommit).toHaveBeenCalledWith({
      width: 350,
      bodyHeight: 150,
    });

    React.act(() => root.unmount());
  });

  it("widens the node when dragged horizontally", () => {
    Object.assign(HTMLElement.prototype, {
      setPointerCapture: () => undefined,
      releasePointerCapture: () => undefined,
      hasPointerCapture: () => false,
    });

    const onDraft = vi.fn();
    const onCommit = vi.fn();
    const container = document.createElement("div");
    const root = createRoot(container);
    React.act(() => {
      root.render(
        <TextareaBodyResizeHandle
          layout={{ width: 300, bodyHeight: 100 }}
          ariaLabel="Resize text field"
          onDraft={onDraft}
          onCommit={onCommit}
        />,
      );
    });

    const handle = container.querySelector("button");
    React.act(() => {
      handle?.dispatchEvent(
        pointerEvent("pointerdown", {
          pointerId: 1,
          button: 0,
          clientX: 200,
          clientY: 80,
        }),
      );
      handle?.dispatchEvent(
        pointerEvent("pointermove", {
          pointerId: 1,
          clientX: 300,
          clientY: 80,
        }),
      );
      handle?.dispatchEvent(
        pointerEvent("pointerup", {
          pointerId: 1,
          clientX: 300,
          clientY: 80,
        }),
      );
    });

    expect(onCommit).toHaveBeenCalledWith({
      width: 400,
      bodyHeight: 100,
    });

    React.act(() => root.unmount());
  });
});
