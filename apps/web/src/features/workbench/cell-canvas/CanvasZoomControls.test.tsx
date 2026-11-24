// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CellCanvas, type CellCanvasHandle } from "./CellCanvas";
import { CanvasZoomControls } from "./CanvasZoomControls";
import type { CellGraph } from "./cell-model";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const mountedRoots = new Set<Root>();

afterEach(async () => {
  await act(async () => {
    for (const root of mountedRoots) root.unmount();
  });
  mountedRoots.clear();
  document.body.replaceChildren();
  vi.restoreAllMocks();
});

async function mount(element: React.ReactElement) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  mountedRoots.add(root);
  await act(async () => root.render(element));
  return { container, root };
}

function buttonByLabel(container: HTMLElement, label: string) {
  return container.querySelector<HTMLButtonElement>(`[aria-label="${label}"]`);
}

describe("CanvasZoomControls", () => {
  it("renders the live zoom percentage and triggers zoom, reset, and fit callbacks", async () => {
    const onZoomIn = vi.fn();
    const onZoomOut = vi.fn();
    const onResetZoom = vi.fn();
    const onFitView = vi.fn();

    const { container } = await mount(
      <CanvasZoomControls
        zoom={1.25}
        onZoomIn={onZoomIn}
        onZoomOut={onZoomOut}
        onResetZoom={onResetZoom}
        onFitView={onFitView}
      />,
    );

    const zoomOut = buttonByLabel(container, "Zoom out");
    const reset = buttonByLabel(container, "Reset zoom to 100%");
    const zoomIn = buttonByLabel(container, "Zoom in");
    const fit = buttonByLabel(container, "Fit view");

    expect(reset?.textContent).toBe("125%");
    expect(zoomOut?.disabled).toBe(false);
    expect(zoomIn?.disabled).toBe(false);
    expect(fit?.disabled).toBe(false);

    await act(async () => zoomOut?.click());
    await act(async () => reset?.click());
    await act(async () => zoomIn?.click());
    await act(async () => fit?.click());

    expect(onZoomOut).toHaveBeenCalledOnce();
    expect(onResetZoom).toHaveBeenCalledOnce();
    expect(onZoomIn).toHaveBeenCalledOnce();
    expect(onFitView).toHaveBeenCalledOnce();
  });

  it("disables Zoom out at minimum zoom and Zoom in at maximum zoom", async () => {
    const atMin = await mount(
      <CanvasZoomControls
        zoom={0.15}
        onZoomIn={() => undefined}
        onZoomOut={() => undefined}
        onResetZoom={() => undefined}
        onFitView={() => undefined}
      />,
    );

    expect(buttonByLabel(atMin.container, "Zoom out")?.disabled).toBe(true);
    expect(buttonByLabel(atMin.container, "Zoom in")?.disabled).toBe(false);
    expect(
      buttonByLabel(atMin.container, "Reset zoom to 100%")?.textContent,
    ).toBe("15%");

    const atMax = await mount(
      <CanvasZoomControls
        zoom={2}
        onZoomIn={() => undefined}
        onZoomOut={() => undefined}
        onResetZoom={() => undefined}
        onFitView={() => undefined}
      />,
    );

    expect(buttonByLabel(atMax.container, "Zoom in")?.disabled).toBe(true);
    expect(buttonByLabel(atMax.container, "Zoom out")?.disabled).toBe(false);
    expect(
      buttonByLabel(atMax.container, "Reset zoom to 100%")?.textContent,
    ).toBe("200%");
  });

  it("disables all controls when the canvas is not ready", async () => {
    const { container } = await mount(
      <CanvasZoomControls
        zoom={1}
        disabled
        onZoomIn={() => undefined}
        onZoomOut={() => undefined}
        onResetZoom={() => undefined}
        onFitView={() => undefined}
      />,
    );

    for (const label of [
      "Zoom out",
      "Reset zoom to 100%",
      "Zoom in",
      "Fit view",
    ]) {
      expect(buttonByLabel(container, label)?.disabled, label).toBe(true);
    }
  });

  it("drives live CellCanvas viewport zoomIn, zoomOut, resetZoom, and fitGraph", async () => {
    const graph: CellGraph = {
      cards: [
        {
          id: "n1",
          title: "Step",
          subtitle: "test.step",
          kind: "operator",
          col: 2,
          row: 2,
          widthCells: 12,
          heightCells: 6,
          ports: [],
        },
      ],
      pipes: [],
    };

    function Harness() {
      const [handle, setHandle] = React.useState<CellCanvasHandle | null>(null);
      const [zoom, setZoom] = React.useState(1);
      return (
        <div>
          <CellCanvas
            graph={graph}
            surfaceById={{ n1: { kind: "operator", configFields: [] } }}
            autoFitOnMount={false}
            onHandleReady={setHandle}
            onViewportZoomChange={setZoom}
          />
          <CanvasZoomControls
            zoom={zoom}
            disabled={handle === null}
            onZoomIn={() => handle?.zoomIn()}
            onZoomOut={() => handle?.zoomOut()}
            onResetZoom={() => handle?.resetZoom()}
            onFitView={() => handle?.fitGraph()}
          />
        </div>
      );
    }

    const { container } = await mount(<Harness />);
    const reset = buttonByLabel(container, "Reset zoom to 100%");
    expect(reset?.textContent).toBe("100%");

    await act(async () => buttonByLabel(container, "Zoom in")?.click());
    expect(reset?.textContent).toBe("125%");

    await act(async () => buttonByLabel(container, "Zoom out")?.click());
    expect(reset?.textContent).toBe("100%");

    await act(async () => buttonByLabel(container, "Zoom out")?.click());
    expect(reset?.textContent).toBe("80%");

    await act(async () => reset?.click());
    expect(reset?.textContent).toBe("100%");

    await act(async () => buttonByLabel(container, "Fit view")?.click());
    expect(reset?.textContent).toBe("92%");
  });
});
