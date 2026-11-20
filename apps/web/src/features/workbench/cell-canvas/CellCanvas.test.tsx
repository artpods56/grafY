// @vitest-environment jsdom

import * as React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CellCanvas, type CellCanvasHandle } from "./CellCanvas";
import type {
  CellCardSurfaceData,
  CellRemotePeerState,
} from "./cell-contracts";
import type { CellGraph } from "./cell-model";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const roots = new Map<Root, HTMLElement>();

afterEach(() => {
  for (const [root, container] of roots) {
    React.act(() => root.unmount());
    container.remove();
  }
  roots.clear();
  document.body.innerHTML = "";
});

const TEST_GRAPH: CellGraph = {
  cards: [
    {
      id: "source",
      title: "Source",
      subtitle: "test.source",
      kind: "operator",
      col: 2,
      row: 2,
      widthCells: 12,
      heightCells: 6,
      resizable: true,
      ports: [
        {
          id: "out",
          name: "Out",
          direction: "output",
          rowOffset: 2,
          artifactTypeId: "scalar.text",
          shape: "one",
        },
      ],
    },
    {
      id: "sink",
      title: "Sink",
      subtitle: "test.sink",
      kind: "operator",
      col: 18,
      row: 2,
      widthCells: 12,
      heightCells: 6,
      resizable: true,
      ports: [
        {
          id: "in",
          name: "In",
          direction: "input",
          rowOffset: 2,
          artifactTypeId: "scalar.text",
          shape: "one",
          required: true,
        },
      ],
    },
  ],
  pipes: [
    {
      id: "pipe-1",
      sourceCardId: "source",
      sourcePortId: "out",
      targetCardId: "sink",
      targetPortId: "in",
      enabled: true,
    },
  ],
};

const TEST_SURFACES: Record<string, CellCardSurfaceData> = {
  source: { kind: "operator", configFields: [] },
  sink: { kind: "operator", configFields: [] },
};

function mountCanvas(
  props: Partial<React.ComponentProps<typeof CellCanvas>> = {},
) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  roots.set(root, container);

  const render = (
    next: Partial<React.ComponentProps<typeof CellCanvas>> = props,
  ) => {
    React.act(() => {
      root.render(
        <CellCanvas graph={TEST_GRAPH} surfaceById={TEST_SURFACES} {...next} />,
      );
    });
  };
  render(props);
  return { container, render };
}

describe("CellCanvas", () => {
  it("renders cards, emits selection changes on click, and syncs controlled selection without loops", () => {
    const onSelectionChange = vi.fn();
    const { container, render } = mountCanvas({
      selectedCardIds: new Set(["source"]),
      selectedPipeIds: new Set(),
      onSelectionChange,
    });

    const sourceCard = container.querySelector<HTMLElement>(
      '[data-card-id="source"]',
    );
    const sinkCard = container.querySelector<HTMLElement>(
      '[data-card-id="sink"]',
    );
    expect(sourceCard?.getAttribute("data-selected")).toBe("true");
    expect(sinkCard?.getAttribute("data-selected")).toBe("false");
    expect(onSelectionChange).not.toHaveBeenCalled();

    React.act(() => {
      const sinkHeader = sinkCard?.querySelector('[data-card-header="true"]');
      sinkHeader?.dispatchEvent(
        new MouseEvent("pointerdown", { bubbles: true, button: 0 }),
      );
    });

    expect(onSelectionChange).toHaveBeenCalledTimes(1);
    const latest = onSelectionChange.mock.calls[0]?.[0];
    expect([...latest.cardIds]).toEqual(["sink"]);
    expect([...latest.pipeIds]).toEqual([]);

    // Updating controlled selection from parent syncs state without re-emitting.
    onSelectionChange.mockClear();
    render({
      selectedCardIds: new Set(["sink"]),
      selectedPipeIds: new Set(["pipe-1"]),
      onSelectionChange,
    });
    expect(onSelectionChange).not.toHaveBeenCalled();
    expect(
      container
        .querySelector('[data-card-id="sink"]')
        ?.getAttribute("data-selected"),
    ).toBe("true");
  });

  it("disables resize grips and keyboard deletion when editable is false", () => {
    const onRemoveCards = vi.fn();
    const onRemovePipes = vi.fn();
    const { container } = mountCanvas({
      editable: false,
      selectedCardIds: new Set(["source"]),
      selectedPipeIds: new Set(["pipe-1"]),
      onRemoveCards,
      onRemovePipes,
    });

    expect(
      container
        .querySelector('[data-cell-canvas="true"]')
        ?.getAttribute("data-editable"),
    ).toBe("false");
    expect(container.querySelector("[data-resize-edge]")).toBeNull();

    React.act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Delete" }));
    });
    expect(onRemoveCards).not.toHaveBeenCalled();
    expect(onRemovePipes).not.toHaveBeenCalled();
  });

  it("renders remote peer cursors and keeps onHandleReady referentially stable across viewport moves", () => {
    const onHandleReady = vi.fn<(handle: CellCanvasHandle | null) => void>();
    const peers: CellRemotePeerState[] = [
      {
        actorId: "actor-1",
        displayName: "Ada",
        color: "#059669",
        cursor: { x: 250, y: 120 },
        activity: "moving_nodes",
        selectedCardIds: ["sink"],
        draggingCards: { sink: { col: 20, row: 3 } },
      },
    ];

    const { container } = mountCanvas({
      remotePeers: peers,
      onHandleReady,
    });

    expect(
      container.querySelector('[data-remote-peer-cursor="actor-1"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('[data-remote-drag-ghost="actor-1:sink"]'),
    ).not.toBeNull();

    const handleCalls = onHandleReady.mock.calls.filter(
      ([arg]) => arg !== null,
    );
    expect(handleCalls).toHaveLength(1);
    const handle = handleCalls[0]?.[0];
    expect(handle).toBeTruthy();

    React.act(() => {
      handle?.viewAt(100, 100, 0.75);
    });

    // Pan/zoom updates viewport state without replacing CellCanvasHandle.
    expect(
      onHandleReady.mock.calls.filter(([arg]) => arg !== null),
    ).toHaveLength(1);
    expect(handle?.viewportHandle.getViewport().zoom).toBe(0.75);
  });
});
