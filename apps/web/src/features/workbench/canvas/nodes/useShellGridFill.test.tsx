// @vitest-environment jsdom

import * as React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles,>(styles: Styles) => styles,
  props: () => ({}),
}));

const gridMocks = vi.hoisted(() => ({
  enabled: true,
  snapSize: true,
  cellSize: 50,
  bypassSnap: false,
}));

vi.mock("../canvas-grid-settings", () => ({
  useOptionalCanvasGridSettings: () => ({
    settings: {
      enabled: gridMocks.enabled,
      showBackground: true,
      snapPosition: true,
      snapSize: gridMocks.snapSize,
      snapWhileDragging: false,
      snapWhileResizing: true,
      allowWorkflowCornerResize: false,
      cellSize: gridMocks.cellSize,
    },
    bypassSnap: gridMocks.bypassSnap,
  }),
}));

import { GRID_SHELL_GUTTER } from "../grid-layout";
import { useShellGridFill } from "./useShellGridFill";

function Probe({
  width,
  onStyles,
}: {
  width: number;
  onStyles: (styles: {
    frameStyle: React.CSSProperties;
    shellStyle: React.CSSProperties;
    paintWidth: number;
    gutter: number;
  }) => void;
}) {
  const { contentRef, frameStyle, shellStyle, paintWidth, gutter } =
    useShellGridFill(width);
  React.useEffect(() => {
    onStyles({ frameStyle, shellStyle, paintWidth, gutter });
  }, [frameStyle, gutter, onStyles, paintWidth, shellStyle]);
  return (
    <div style={frameStyle} data-testid="frame">
      <article style={shellStyle} data-testid="shell">
        <div
          ref={contentRef}
          data-testid="content"
          style={{ height: 310, width: "100%" }}
        />
      </article>
    </div>
  );
}

describe("useShellGridFill", () => {
  const roots: ReturnType<typeof createRoot>[] = [];

  afterEach(() => {
    React.act(() => {
      for (const root of roots.splice(0)) root.unmount();
    });
    gridMocks.enabled = true;
    gridMocks.snapSize = true;
    gridMocks.cellSize = 50;
    gridMocks.bypassSnap = false;
  });

  it("pads the frame to whole cells and insets the painted shell", () => {
    const styles: Array<{
      frameStyle: React.CSSProperties;
      shellStyle: React.CSSProperties;
      paintWidth: number;
      gutter: number;
    }> = [];
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    roots.push(root);

    // jsdom layout is zero-sized; stub offsetHeight + RO.
    const offsetDescriptor = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      "offsetHeight",
    );
    Object.defineProperty(HTMLElement.prototype, "offsetHeight", {
      configurable: true,
      get(this: HTMLElement) {
        return this.dataset?.testid === "content" ? 310 : 0;
      },
    });
    class ImmediateResizeObserver {
      private readonly callback: ResizeObserverCallback;
      constructor(callback: ResizeObserverCallback) {
        this.callback = callback;
      }
      observe(target: Element) {
        this.callback(
          [{ target } as ResizeObserverEntry],
          this as unknown as ResizeObserver,
        );
      }
      unobserve() {}
      disconnect() {}
    }
    const previousRO = globalThis.ResizeObserver;
    globalThis.ResizeObserver =
      ImmediateResizeObserver as unknown as typeof ResizeObserver;

    React.act(() => {
      root.render(
        <Probe
          width={310}
          onStyles={(next) =>
            styles.push({
              frameStyle: { ...next.frameStyle },
              shellStyle: { ...next.shellStyle },
              paintWidth: next.paintWidth,
              gutter: next.gutter,
            })
          }
        />,
      );
    });

    const latest = styles.at(-1);
    // content 310 + gutters 12 → 322 → ceil to 350
    expect(latest?.frameStyle.width).toBe(300);
    expect(latest?.frameStyle.height).toBe(350);
    expect(latest?.frameStyle.minHeight).toBe(350);
    expect(latest?.frameStyle.padding).toBe(GRID_SHELL_GUTTER);
    expect(latest?.shellStyle.width).toBe("100%");
    // The plate fills the rest of the frame column under the name row.
    expect(latest?.shellStyle.flex).toBe("1 1 auto");
    expect(latest?.gutter).toBe(GRID_SHELL_GUTTER);
    expect(latest?.paintWidth).toBe(300 - GRID_SHELL_GUTTER * 2);

    if (offsetDescriptor) {
      Object.defineProperty(
        HTMLElement.prototype,
        "offsetHeight",
        offsetDescriptor,
      );
    }
    globalThis.ResizeObserver = previousRO;
    document.body.removeChild(container);
  });

  it("grows an extra cell when gutters push content past the boundary", () => {
    const styles: Array<{ frameStyle: React.CSSProperties }> = [];
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    roots.push(root);

    Object.defineProperty(HTMLElement.prototype, "offsetHeight", {
      configurable: true,
      get(this: HTMLElement) {
        // 339 + 12 = 351 → ceil to 400
        return this.dataset?.testid === "content" ? 339 : 0;
      },
    });
    class ImmediateResizeObserver {
      private readonly callback: ResizeObserverCallback;
      constructor(callback: ResizeObserverCallback) {
        this.callback = callback;
      }
      observe(target: Element) {
        this.callback(
          [{ target } as ResizeObserverEntry],
          this as unknown as ResizeObserver,
        );
      }
      unobserve() {}
      disconnect() {}
    }
    const previousRO = globalThis.ResizeObserver;
    globalThis.ResizeObserver =
      ImmediateResizeObserver as unknown as typeof ResizeObserver;

    React.act(() => {
      root.render(
        <Probe
          width={300}
          onStyles={(next) =>
            styles.push({ frameStyle: { ...next.frameStyle } })
          }
        />,
      );
    });

    expect(styles.at(-1)?.frameStyle.height).toBe(400);

    globalThis.ResizeObserver = previousRO;
    document.body.removeChild(container);
  });

  it("skips fill and gutter when size snap is disabled", () => {
    gridMocks.snapSize = false;
    const styles: Array<{
      frameStyle: React.CSSProperties;
      shellStyle: React.CSSProperties;
      gutter: number;
    }> = [];
    const container = document.createElement("div");
    const root = createRoot(container);
    roots.push(root);

    React.act(() => {
      root.render(
        <Probe
          width={300}
          onStyles={(next) =>
            styles.push({
              frameStyle: { ...next.frameStyle },
              shellStyle: { ...next.shellStyle },
              gutter: next.gutter,
            })
          }
        />,
      );
    });

    const latest = styles.at(-1);
    expect(latest?.frameStyle.width).toBe(300);
    expect(latest?.frameStyle.padding).toBeUndefined();
    expect(latest?.frameStyle.minHeight).toBeUndefined();
    expect(latest?.shellStyle.width).toBe(300);
    expect(latest?.gutter).toBe(0);
  });

  it("stops exposing a measured fill height when size snap is disabled", () => {
    const styles: Array<{
      frameStyle: React.CSSProperties;
      shellStyle: React.CSSProperties;
      gutter: number;
    }> = [];
    const container = document.createElement("div");
    const root = createRoot(container);
    roots.push(root);

    Object.defineProperty(HTMLElement.prototype, "offsetHeight", {
      configurable: true,
      get(this: HTMLElement) {
        return this.dataset?.testid === "content" ? 310 : 0;
      },
    });

    React.act(() => {
      root.render(
        <Probe
          width={300}
          onStyles={(next) =>
            styles.push({
              frameStyle: { ...next.frameStyle },
              shellStyle: { ...next.shellStyle },
              gutter: next.gutter,
            })
          }
        />,
      );
    });
    expect(styles.at(-1)?.frameStyle.height).toBe(350);

    gridMocks.snapSize = false;
    React.act(() => {
      root.render(
        <Probe
          width={300}
          onStyles={(next) =>
            styles.push({
              frameStyle: { ...next.frameStyle },
              shellStyle: { ...next.shellStyle },
              gutter: next.gutter,
            })
          }
        />,
      );
    });

    expect(styles.at(-1)?.frameStyle.height).toBeUndefined();
    expect(styles.at(-1)?.frameStyle.minHeight).toBeUndefined();
    expect(styles.at(-1)?.shellStyle.flex).toBeUndefined();
    expect(styles.at(-1)?.gutter).toBe(0);
  });
});
