// @vitest-environment jsdom

import * as React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useCellCardState } from "./CellCanvasContext";

import {
  CellCanvas,
  DEFAULT_CELL_GLASS_LOOK,
  type CellCanvasHandle,
} from "./CellCanvas";
import type {
  CellCardSurfaceData,
  CellRemotePeerState,
} from "./cell-contracts";
import {
  ARTIFACT_CARD_OUTPUT_PORT_ID,
  artifactCardOutputRow,
  portAnchorCenter,
  punchedPipePoints,
  punchedPortCardCentre,
  punchedPortWorldCenter,
  type CellGraph,
} from "./cell-model";

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
  it("pans without re-rendering a subscriber to an unchanged card", () => {
    const renderCard = vi.fn();
    function CardSubscriber() {
      const state = useCellCardState("source");
      renderCard(state);
      return null;
    }

    const { container } = mountCanvas({ children: <CardSubscriber /> });
    const canvas = container.querySelector<HTMLElement>("[data-cell-canvas]")!;
    const world = container.querySelector<HTMLElement>("[data-cell-viewport]")!;
    const initialTransform = world.style.transform;
    expect(renderCard).toHaveBeenCalled();
    renderCard.mockClear();

    React.act(() => {
      canvas.dispatchEvent(new WheelEvent("wheel", { deltaX: 40 }));
    });
    expect(world.style.transform).not.toBe(initialTransform);
    expect(renderCard).not.toHaveBeenCalled();
  });

  it.each(["pointerup", "pointercancel"])(
    "pans once per frame and applies the last move on %s",
    (endEvent) => {
      vi.useFakeTimers({
        toFake: ["requestAnimationFrame", "cancelAnimationFrame"],
      });
      try {
        const { container } = mountCanvas({ autoFitOnMount: false });
        const canvas = container.querySelector("[data-cell-canvas]")!;
        const world = container.querySelector<HTMLElement>(
          "[data-cell-viewport]",
        )!;
        const initialTransform = world.style.transform;
        const move = (clientX: number, clientY: number) => {
          React.act(() => {
            window.dispatchEvent(
              new PointerEvent("pointermove", {
                pointerId: 7,
                clientX,
                clientY,
              }),
            );
          });
        };

        React.act(() => {
          canvas.dispatchEvent(
            new PointerEvent("pointerdown", { bubbles: true, pointerId: 7 }),
          );
        });
        move(10, 5);
        move(20, 10);
        expect(world.style.transform).toBe(initialTransform);

        React.act(() => {
          vi.advanceTimersToNextFrame();
        });
        expect(world.style.transform).toBe(
          "translate3d(20px, 10px, 0) scale(1)",
        );

        move(35, 15);
        React.act(() => {
          window.dispatchEvent(new PointerEvent(endEvent, { pointerId: 7 }));
        });
        expect(world.style.transform).toBe(
          "translate3d(35px, 15px, 0) scale(1)",
        );

        move(55, 30);
        React.act(() => {
          vi.advanceTimersToNextFrame();
        });
        expect(world.style.transform).toBe(
          "translate3d(35px, 15px, 0) scale(1)",
        );
      } finally {
        vi.useRealTimers();
      }
    },
  );

  it("keeps a peer's outline mounted while it fades out", () => {
    vi.useFakeTimers();
    try {
      const peer: CellRemotePeerState = {
        actorId: "actor",
        displayName: "Ada",
        color: "#059669",
        cursor: null,
        activity: "moving_nodes",
        selectedCardIds: ["sink"],
        draggingCards: { sink: { col: 22, row: 2 } },
      };
      const { container, render } = mountCanvas({ remotePeers: [peer] });
      const selector = '[data-remote-drag-ghost="actor:sink"]';
      const outline = container.querySelector(selector);
      expect(outline?.hasAttribute("data-ending-style")).toBe(false);

      render({ remotePeers: [] });
      expect(container.querySelector(selector)).toBe(outline);
      expect(outline?.hasAttribute("data-ending-style")).toBe(true);

      render({ remotePeers: [peer] });
      React.act(() => vi.advanceTimersByTime(150));
      expect(container.querySelector(selector)).toBe(outline);
      expect(outline?.hasAttribute("data-ending-style")).toBe(false);

      render({ remotePeers: [] });
      React.act(() => vi.advanceTimersByTime(150));
      expect(container.querySelector(selector)).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("animates the actual card during a remote drag and holds it across release", () => {
    vi.useFakeTimers();
    try {
      const peer: CellRemotePeerState = {
        actorId: "actor",
        displayName: "Ada",
        color: "#059669",
        cursor: null,
        activity: "moving_nodes",
        selectedCardIds: ["sink"],
        draggingCards: { sink: { col: 22, row: 2 } },
      };
      const { container, render } = mountCanvas({ remotePeers: [peer] });
      const card = container.querySelector<HTMLElement>(
        '[data-card-id="sink"]',
      );
      const readX = () =>
        Number(card?.style.transform.match(/translate3d\(([^p]+)px/)?.[1]);
      expect(readX()).toBe(450);

      React.act(() => vi.advanceTimersByTime(96));
      expect(readX()).toBeGreaterThan(450);
      expect(readX()).toBeLessThan(550);

      render({
        remotePeers: [{ ...peer, activity: "idle", draggingCards: {} }],
      });
      React.act(() => vi.advanceTimersByTime(64));
      expect(readX()).toBeGreaterThan(450);

      const committedGraph = {
        ...TEST_GRAPH,
        cards: TEST_GRAPH.cards.map((item) =>
          item.id === "sink" ? { ...item, col: 22 } : item,
        ),
      };
      render({ graph: committedGraph });
      React.act(() => vi.advanceTimersByTime(1000));
      expect(readX()).toBe(550);
    } finally {
      vi.useRealTimers();
    }
  });

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

  it("leaves recessed wells in the glass by default", () => {
    const { container } = mountCanvas();
    expect(container.querySelector("[data-cell-well]")).not.toBeNull();
    expect(
      container
        .querySelector('[data-port-id="out"]')
        ?.getAttribute("data-port-well"),
    ).toBeNull();
  });

  it("punches ports into the cards, bores no well and runs pipes into the holes", () => {
    const { container } = mountCanvas({
      look: { ...DEFAULT_CELL_GLASS_LOOK, well: "punched" },
    });
    // The frost runs unbroken: the only wells are the cards' own holes.
    const wells = [...container.querySelectorAll("[data-cell-well]")];
    expect(wells).toHaveLength(2);
    for (const well of wells) {
      expect(well.closest("[data-punched-socket]")).not.toBeNull();
    }

    const out = container.querySelector<HTMLElement>('[data-port-id="out"]');
    const input = container.querySelector<HTMLElement>('[data-port-id="in"]');
    expect(out?.getAttribute("data-port-well")).toBe("punched");
    // Source: 12 cells wide, so its output's hole is at 300 - 22 = 278.
    expect(out?.style.left).toBe(`${278 - 15}px`);
    expect(input?.style.left).toBe(`${22 - 15}px`);
    expect(
      out?.querySelector('[data-punched-socket="connected"]'),
    ).not.toBeNull();
    expect(container.querySelector("[data-port-stem]")).toBeNull();

    // The routed pipe is carried on from the gutter into both holes.
    const path = container
      .querySelector('[data-pipe="pipe-1"] path')
      ?.getAttribute("d");
    expect(path?.startsWith("M328,112.5")).toBe(true);
    expect(path?.endsWith("L472,112.5")).toBe(true);
  });

  it("routes a flush artifact corner output into its hole instead of docking it when punched", () => {
    const outputRow = artifactCardOutputRow(6);
    const [source, sink] = TEST_GRAPH.cards;
    const flush: CellGraph = {
      cards: [
        {
          ...source!,
          ports: [
            {
              ...source!.ports[0]!,
              id: ARTIFACT_CARD_OUTPUT_PORT_ID,
              rowOffset: outputRow,
            },
          ],
        },
        {
          ...sink!,
          col: source!.col + source!.widthCells,
          ports: [{ ...sink!.ports[0]!, rowOffset: outputRow }],
        },
      ],
      pipes: [
        { ...TEST_GRAPH.pipes[0]!, sourcePortId: ARTIFACT_CARD_OUTPUT_PORT_ID },
      ],
    };
    const pipeId = flush.pipes[0]!.id;

    // In the gutter the two ports share a row, so the seam bridges them.
    const recessed = mountCanvas({ graph: flush });
    expect(
      recessed.container.querySelector(`[data-docked-join="${pipeId}"]`),
    ).not.toBeNull();

    // Punched, the output sits in the corner, below the row's midline: no
    // bridge, a routed pipe that ends in the corner hole.
    const punched = mountCanvas({
      graph: flush,
      look: { ...DEFAULT_CELL_GLASS_LOOK, well: "punched" },
    });
    expect(
      punched.container.querySelector(`[data-docked-join="${pipeId}"]`),
    ).toBeNull();
    const corner = punchedPortWorldCenter(
      flush.cards[0]!,
      flush.cards[0]!.ports[0]!,
    );
    const path = punched.container
      .querySelector(`[data-pipe="${pipeId}"] path`)
      ?.getAttribute("d");
    expect(path?.startsWith(`M${corner.x},${corner.y}`)).toBe(true);
  });

  it("glows a punched port's hole on hover, with no pipe until a drag", () => {
    const { container } = mountCanvas({
      graph: { ...TEST_GRAPH, pipes: [] },
      look: { ...DEFAULT_CELL_GLASS_LOOK, well: "punched" },
    });
    const input = container.querySelector<HTMLElement>('[data-port-id="in"]');
    const glow = () =>
      input?.querySelector("[data-port-glow]")?.getAttribute("data-port-glow");
    expect(glow()).toBe("off");
    React.act(() => {
      input?.dispatchEvent(new PointerEvent("pointerover", { bubbles: true }));
    });
    expect(glow()).toBe("on");
    expect(input?.querySelector("[data-cell-well-stub]")).toBeNull();
    React.act(() => {
      input?.dispatchEvent(
        new PointerEvent("pointerout", {
          bubbles: true,
          relatedTarget: document.body,
        }),
      );
    });
    expect(glow()).toBe("off");
  });

  it("snaps a connection drag to a punched hole's centre", () => {
    const onConnect = vi.fn();
    const graph: CellGraph = { ...TEST_GRAPH, pipes: [] };
    const { container } = mountCanvas({
      graph,
      look: { ...DEFAULT_CELL_GLASS_LOOK, well: "punched" },
      onConnect,
    });
    const canvas = container.querySelector<HTMLElement>(
      '[data-cell-canvas="true"]',
    );
    canvas!.getBoundingClientRect = () => new DOMRect(0, 0, 1000, 600);
    const out = container.querySelector<HTMLElement>('[data-port-id="out"]');
    const viewport = container.querySelector<HTMLElement>(
      '[data-cell-viewport="true"]',
    );
    const match =
      /translate3d\((-?[\d.]+)px, (-?[\d.]+)px, 0\) scale\(([\d.]+)\)/.exec(
        viewport?.style.transform ?? "",
      );
    expect(match).not.toBeNull();
    const [vx, vy, zoom] = [
      Number(match![1]),
      Number(match![2]),
      Number(match![3]),
    ];
    // A world point inside the sink's hole (472, 112.5) but outside the old
    // gutter snap radius (437.5, 112.5 is 30.5 away).
    const toClient = (x: number, y: number) => ({
      clientX: vx + x * zoom,
      clientY: vy + y * zoom,
    });
    React.act(() => {
      out?.dispatchEvent(
        new PointerEvent("pointerdown", {
          bubbles: true,
          button: 0,
          pointerId: 1,
          ...toClient(328, 112.5),
        }),
      );
    });
    React.act(() => {
      window.dispatchEvent(
        new PointerEvent("pointermove", {
          bubbles: true,
          pointerId: 1,
          ...toClient(470, 114),
        }),
      );
    });
    expect(
      container
        .querySelector('[data-port-id="in"]')
        ?.getAttribute("data-port-hot"),
    ).toBe("true");
    // The hole under the drag glows and shows the pipe coming in.
    const target = container.querySelector('[data-port-id="in"]');
    expect(
      target?.querySelector("[data-port-glow]")?.getAttribute("data-port-glow"),
    ).toBe("on");
    expect(target?.querySelector("[data-cell-well-stub]")).not.toBeNull();
    // The pipe being wired is already in the source's hole, and runs on under
    // the cards: its plane sits over the frost (z 2) and under the cards (z 4).
    expect(
      out?.querySelector('[data-punched-socket="connected"]'),
    ).not.toBeNull();
    const preview = container.querySelector<HTMLElement>(
      '[data-cell-connection-preview="true"]',
    );
    expect(preview).not.toBeNull();
    const world = container.querySelector('[data-cell-viewport="true"]');
    expect(
      preview!.compareDocumentPosition(world!) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    React.act(() => {
      window.dispatchEvent(
        new PointerEvent("pointerup", {
          bubbles: true,
          pointerId: 1,
          ...toClient(470, 114),
        }),
      );
    });
    expect(onConnect).toHaveBeenCalledTimes(1);
  });
});

describe("CellCanvas artifact sequences", () => {
  const artifactCard = (id: string, col: number, row: number) => ({
    id,
    title: "PNG image",
    subtitle: "",
    kind: "artifact" as const,
    col,
    row,
    widthCells: 10,
    heightCells: 8,
    resizable: true,
    ports: [],
  });
  const image = (itemCount = 1): CellCardSurfaceData => ({
    kind: "artifact",
    previewKind: "image",
    artifactTypeId: "file.png",
    typeLabel: "PNG image",
    ...(itemCount > 1
      ? {
          itemCount,
          stackItems: Array.from({ length: itemCount }, (_, index) => ({
            artifactId: `item-${index}`,
            label: `#${index + 1}`,
          })),
        }
      : {}),
  });
  // `left` and `stack` sit flush side by side; `loose` stands apart.
  const graph: CellGraph = {
    cards: [
      artifactCard("left", 2, 2),
      artifactCard("stack", 12, 2),
      artifactCard("loose", 40, 2),
    ],
    pipes: [],
  };
  const surfaces = { left: image(), stack: image(3), loose: image() };

  function worldToClient(container: HTMLElement) {
    const viewport = container.querySelector<HTMLElement>(
      '[data-cell-viewport="true"]',
    );
    const match =
      /translate3d\((-?[\d.]+)px, (-?[\d.]+)px, 0\) scale\(([\d.]+)\)/.exec(
        viewport?.style.transform ?? "",
      );
    expect(match).not.toBeNull();
    const [vx, vy, zoom] = [
      Number(match![1]),
      Number(match![2]),
      Number(match![3]),
    ];
    return (x: number, y: number) => ({
      clientX: vx + x * zoom,
      clientY: vy + y * zoom,
    });
  }

  // The stack alone in its rows, with open canvas either side.
  const openGraph: CellGraph = {
    cards: [artifactCard("stack", 12, 2), artifactCard("other", 12, 20)],
    pipes: [],
  };
  const openSurfaces = { stack: image(3), other: image() };

  it("spreads a stack in place from its header count and closes it on Escape", () => {
    const { container } = mountCanvas({
      graph: openGraph,
      surfaceById: openSurfaces,
    });
    const count = container.querySelector<HTMLElement>(
      '[data-card-id="stack"] [data-card-header="true"] [data-artifact-stack-count="3"]',
    );
    expect(count?.tagName).toBe("BUTTON");
    expect(count?.hasAttribute("disabled")).toBe(false);
    React.act(() => count?.click());
    const spread = container.querySelector<HTMLElement>(
      '[data-artifact-sequence-spread="stack"]',
    );
    expect(spread).not.toBeNull();
    expect(spread?.querySelectorAll("[data-sequence-item]")).toHaveLength(3);
    // The collapsed card gives way to its spread, so nothing peeks out.
    expect(container.querySelector('[data-card-id="stack"]')).toBeNull();
    React.act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });
    expect(
      container.querySelector("[data-artifact-sequence-spread]"),
    ).toBeNull();
    expect(container.querySelector('[data-card-id="stack"]')).not.toBeNull();
  });

  it("stays open when the canvas background is clicked and closes via the Stack button", () => {
    const { container } = mountCanvas({
      graph: openGraph,
      surfaceById: openSurfaces,
    });
    React.act(() =>
      container
        .querySelector<HTMLElement>('[data-artifact-stack-count="3"]')
        ?.click(),
    );
    expect(
      container.querySelector("[data-artifact-sequence-spread]"),
    ).not.toBeNull();
    const canvas = container.querySelector<HTMLElement>(
      '[data-cell-canvas="true"]',
    )!;
    React.act(() => {
      canvas.dispatchEvent(
        new PointerEvent("pointerdown", {
          bubbles: true,
          button: 0,
          pointerId: 9,
          clientX: 5,
          clientY: 5,
        }),
      );
    });
    // Clicking the canvas keeps the spread open so another card can be dragged into it.
    expect(
      container.querySelector("[data-artifact-sequence-spread]"),
    ).not.toBeNull();
    React.act(() => {
      container
        .querySelector<HTMLElement>('[data-sequence-collapse="true"]')
        ?.click();
    });
    expect(
      container.querySelector("[data-artifact-sequence-spread]"),
    ).toBeNull();
  });

  it("inserts a compatible canvas card dropped onto an open spread at the hovered slot", () => {
    const onInsertArtifactCardIntoSequence = vi.fn();
    const onMoveCards = vi.fn();
    const dragInGraph: CellGraph = {
      cards: [artifactCard("stack", 12, 2), artifactCard("loose", 12, 16)],
      pipes: [],
    };
    const { container } = mountCanvas({
      graph: dragInGraph,
      surfaceById: { stack: image(3), loose: image() },
      canMergeArtifactCards: (source, target) =>
        source === "loose" && target === "stack",
      onInsertArtifactCardIntoSequence,
      onMoveCards,
    });
    const canvas = container.querySelector<HTMLElement>(
      '[data-cell-canvas="true"]',
    )!;
    canvas.getBoundingClientRect = () => new DOMRect(0, 0, 1000, 600);
    React.act(() =>
      container
        .querySelector<HTMLElement>('[data-artifact-stack-count="3"]')
        ?.click(),
    );
    const toClient = worldToClient(container);
    const looseHeader = container.querySelector<HTMLElement>(
      '[data-card-id="loose"] [data-card-header="true"]',
    )!;
    React.act(() => {
      looseHeader.dispatchEvent(
        new PointerEvent("pointerdown", {
          bubbles: true,
          button: 0,
          pointerId: 12,
          ...toClient(15 * 25, 17 * 25),
        }),
      );
    });
    // Drop between slot 0 (cols 12..22) and slot 1 (cols 22..32) -> slot 1, index 1.
    React.act(() => {
      window.dispatchEvent(
        new PointerEvent("pointermove", {
          bubbles: true,
          pointerId: 12,
          ...toClient(22 * 25, 6 * 25),
        }),
      );
    });
    expect(
      container.querySelector('[data-sequence-external-insert="1"]'),
    ).not.toBeNull();
    // The drop joins the sequence, so no grid landing is shown under it.
    expect(
      container.querySelector(
        '[data-cell-ghost="loose"]:not([data-ending-style])',
      ),
    ).toBeNull();
    React.act(() => {
      window.dispatchEvent(
        new PointerEvent("pointerup", {
          bubbles: true,
          pointerId: 12,
          ...toClient(22 * 25, 6 * 25),
        }),
      );
    });
    expect(onInsertArtifactCardIntoSequence).toHaveBeenCalledWith(
      "loose",
      "stack",
      1,
    );
    expect(onMoveCards).not.toHaveBeenCalled();
  });

  it("moves an expanded spread via its top drag handle through onMoveCards", () => {
    const onMoveCards = vi.fn();
    const { container } = mountCanvas({
      graph: openGraph,
      surfaceById: openSurfaces,
      onMoveCards,
    });
    const canvas = container.querySelector<HTMLElement>(
      '[data-cell-canvas="true"]',
    );
    canvas!.getBoundingClientRect = () => new DOMRect(0, 0, 1000, 600);
    React.act(() =>
      container
        .querySelector<HTMLElement>('[data-artifact-stack-count="3"]')
        ?.click(),
    );
    const handle = container.querySelector<HTMLElement>(
      '[data-sequence-move="true"]',
    );
    expect(handle).not.toBeNull();
    const toClient = worldToClient(container);
    React.act(() => {
      handle!.dispatchEvent(
        new PointerEvent("pointerdown", {
          bubbles: true,
          button: 0,
          pointerId: 11,
          ...toClient(500, 100),
        }),
      );
    });
    React.act(() => {
      window.dispatchEvent(
        new PointerEvent("pointermove", {
          bubbles: true,
          pointerId: 11,
          ...toClient(500 + 3 * 25, 100 + 2 * 25),
        }),
      );
    });
    React.act(() => {
      window.dispatchEvent(
        new PointerEvent("pointerup", {
          bubbles: true,
          pointerId: 11,
          ...toClient(500 + 3 * 25, 100 + 2 * 25),
        }),
      );
    });
    expect(onMoveCards).toHaveBeenCalledWith([
      { cardId: "stack", col: 15, row: 4 },
    ]);
  });

  it("disables the count of a stack boxed in too tightly to spread", () => {
    // `left` sits flush against it and `loose` 18 cells to its right.
    const { container } = mountCanvas({ graph, surfaceById: surfaces });
    const count = container.querySelector<HTMLElement>(
      '[data-artifact-stack-count="3"]',
    );
    expect(count?.hasAttribute("disabled")).toBe(true);
    expect(count?.getAttribute("title")).toBe(
      "Move card into open space to spread",
    );
    React.act(() => count?.click());
    expect(
      container.querySelector("[data-artifact-sequence-spread]"),
    ).toBeNull();
  });

  it("closes the spread when its card is left holding one item", () => {
    const { container, render } = mountCanvas({
      graph: openGraph,
      surfaceById: openSurfaces,
    });
    React.act(() =>
      container
        .querySelector<HTMLElement>('[data-artifact-stack-count="3"]')
        ?.click(),
    );
    render({
      graph: openGraph,
      surfaceById: { ...openSurfaces, stack: image() },
    });
    expect(
      container.querySelector("[data-artifact-sequence-spread]"),
    ).toBeNull();
    render({ graph: openGraph, surfaceById: openSurfaces });
    expect(
      container.querySelector("[data-artifact-sequence-spread]"),
    ).toBeNull();
  });

  it("offers one merge button for a whole flush run", () => {
    const onMergeArtifactCardRun = vi.fn();
    const runGraph: CellGraph = {
      cards: [
        artifactCard("left", 2, 2),
        artifactCard("stack", 12, 2),
        artifactCard("right", 22, 2),
        artifactCard("loose", 40, 2),
      ],
      pipes: [],
    };
    const { container } = mountCanvas({
      graph: runGraph,
      surfaceById: { ...surfaces, right: image() },
      canMergeArtifactCards: () => true,
      onMergeArtifactCards: () => {},
      onMergeArtifactCardRun,
    });
    const outlines = container.querySelectorAll(
      "[data-artifact-merge-suggestion]",
    );
    expect(
      [...outlines].map((outline) =>
        outline.getAttribute("data-artifact-merge-suggestion"),
      ),
    ).toEqual(["left|stack|right"]);
    const buttons = container.querySelectorAll<HTMLElement>(
      "[data-artifact-merge-button]",
    );
    expect(buttons).toHaveLength(1);
    const button = buttons[0]!;
    expect(button.textContent).toBe("Stack 5");
    expect(button.getAttribute("data-cell-canvas-chrome")).toBe("true");
    // Under the run's middle, on the plates' bottom edge.
    const anchor = button.parentElement!;
    expect(anchor.style.left).toBe(`${17 * 25}px`);
    expect(anchor.style.top).toBe(`${10 * 25 - 4}px`);
    React.act(() => button.click());
    expect(onMergeArtifactCardRun).toHaveBeenCalledWith(
      ["left", "stack", "right"],
      "left",
    );
  });

  it("offers nothing on a read-only canvas", () => {
    const { container } = mountCanvas({
      graph,
      surfaceById: surfaces,
      editable: false,
      canMergeArtifactCards: () => true,
      onMergeArtifactCards: () => {},
      onMergeArtifactCardRun: () => {},
    });
    expect(
      container.querySelector("[data-artifact-merge-suggestion]"),
    ).toBeNull();
  });

  it("merges a card dropped onto a sequence instead of moving it", () => {
    const onMergeArtifactCards = vi.fn();
    const onMoveCards = vi.fn();
    const { container } = mountCanvas({
      graph,
      surfaceById: surfaces,
      canMergeArtifactCards: (source, target) =>
        source === "loose" && target === "stack",
      onMergeArtifactCards,
      onMoveCards,
    });
    const canvas = container.querySelector<HTMLElement>(
      '[data-cell-canvas="true"]',
    );
    canvas!.getBoundingClientRect = () => new DOMRect(0, 0, 1000, 600);
    const toClient = worldToClient(container);
    // A card is picked up by its header.
    const loose = container.querySelector<HTMLElement>(
      '[data-card-id="loose"] [data-card-header="true"]',
    );
    React.act(() => {
      loose?.dispatchEvent(
        new PointerEvent("pointerdown", {
          bubbles: true,
          button: 0,
          pointerId: 3,
          ...toClient(1050, 60),
        }),
      );
    });
    // Over the stack's plate.
    React.act(() => {
      window.dispatchEvent(
        new PointerEvent("pointermove", {
          bubbles: true,
          pointerId: 3,
          ...toClient(400, 120),
        }),
      );
    });
    const target = container.querySelector(
      '[data-artifact-merge-target="stack"]',
    );
    expect(target).not.toBeNull();
    expect(target?.textContent).toContain("Merge into sequence (4)");
    React.act(() => {
      window.dispatchEvent(
        new PointerEvent("pointerup", {
          bubbles: true,
          pointerId: 3,
          ...toClient(400, 120),
        }),
      );
    });
    expect(onMergeArtifactCards).toHaveBeenCalledWith(
      "loose",
      "stack",
      "target-first",
    );
    expect(onMoveCards).not.toHaveBeenCalled();
    expect(container.querySelector("[data-artifact-merge-target]")).toBeNull();
  });
});

describe("punched pipe geometry", () => {
  const card = TEST_GRAPH.cards[1]!;
  const port = card.ports[0]!;

  it("centres a punched port 22px inside its card on its row", () => {
    expect(punchedPortWorldCenter(card, port)).toEqual({ x: 472, y: 112.5 });
    expect(
      punchedPortWorldCenter(
        TEST_GRAPH.cards[0]!,
        TEST_GRAPH.cards[0]!.ports[0]!,
      ),
    ).toEqual({ x: 328, y: 112.5 });
    expect(punchedPortWorldCenter(card, port, { x: 10, y: -5 })).toEqual({
      x: 482,
      y: 107.5,
    });
  });

  it("grows a sideways end into the hole and leads a vertical end in", () => {
    const source = { x: 332, y: 112.5 };
    const target = { x: 468, y: 162.5 };
    expect(
      punchedPipePoints(
        [
          { x: 362.5, y: 112.5 },
          { x: 400, y: 112.5 },
          { x: 400, y: 162.5 },
          { x: 437.5, y: 162.5 },
        ],
        source,
        target,
      ),
    ).toEqual([source, { x: 400, y: 112.5 }, { x: 400, y: 162.5 }, target]);
    // An end that leaves its gutter cell downward keeps it and gains a lead-in.
    expect(
      punchedPipePoints(
        [
          { x: 362.5, y: 112.5 },
          { x: 362.5, y: 162.5 },
          { x: 437.5, y: 162.5 },
        ],
        source,
        target,
      ),
    ).toEqual([source, { x: 362.5, y: 112.5 }, { x: 362.5, y: 162.5 }, target]);
  });

  it("pins an artifact card's output hole 22px in from its right and bottom", () => {
    const card = {
      id: "photo",
      kind: "artifact" as const,
      title: "JPEG image",
      subtitle: "",
      col: 2,
      row: 4,
      widthCells: 10,
      heightCells: 8,
      ports: [],
    };
    const output = {
      id: ARTIFACT_CARD_OUTPUT_PORT_ID,
      name: "artifact",
      direction: "output" as const,
      rowOffset: artifactCardOutputRow(8),
      artifactTypeId: "image.jpeg",
      shape: "one" as const,
    };
    // Card box 50..300 × 100..300: the hole sits 22px in from both corners.
    expect(punchedPortCardCentre(card, output)).toEqual({ x: 228, y: 178 });
    expect(punchedPortWorldCenter(card, output)).toEqual({ x: 278, y: 278 });
    expect(portAnchorCenter(card, output, true)).toEqual({ x: 278, y: 278 });
    // A resize moves it with the corner.
    expect(
      punchedPortCardCentre({ widthCells: 12, heightCells: 10 }, output),
    ).toEqual({ x: 278, y: 228 });
    // Recessed and flat, it keeps its row's gutter cell.
    expect(portAnchorCenter(card, output, false)).toEqual({
      x: 312.5,
      y: 262.5,
    });
    // Any other output stays on its row midline.
    expect(
      punchedPortWorldCenter(card, { ...output, id: "out", rowOffset: 3 }),
    ).toEqual({ x: 278, y: 187.5 });
  });

  it("leaves a corner hole horizontally and steps to the gutter row outside the card", () => {
    // The hole (278, 278) sits 15.5px below its gutter row (262.5).
    const source = { x: 278, y: 278 };
    const target = { x: 432, y: 212.5 };
    // Off sideways into a vertical turn: the first run slides onto the hole's row.
    expect(
      punchedPipePoints(
        [
          { x: 312.5, y: 262.5 },
          { x: 362.5, y: 262.5 },
          { x: 362.5, y: 212.5 },
          { x: 412.5, y: 212.5 },
        ],
        source,
        target,
      ),
    ).toEqual([source, { x: 362.5, y: 278 }, { x: 362.5, y: 212.5 }, target]);
    // Straight across with no turn: a step in the gutter column, past the card.
    expect(
      punchedPipePoints(
        [
          { x: 312.5, y: 262.5 },
          { x: 412.5, y: 262.5 },
        ],
        source,
        { x: 432, y: 262.5 },
      ),
    ).toEqual([
      source,
      { x: 312.5, y: 278 },
      { x: 312.5, y: 262.5 },
      { x: 432, y: 262.5 },
    ]);
    // Off downward: the vertical run stretches to the hole's row.
    expect(
      punchedPipePoints(
        [
          { x: 312.5, y: 262.5 },
          { x: 312.5, y: 337.5 },
          { x: 412.5, y: 337.5 },
        ],
        source,
        { x: 432, y: 337.5 },
      ),
    ).toEqual([
      source,
      { x: 312.5, y: 278 },
      { x: 312.5, y: 337.5 },
      { x: 432, y: 337.5 },
    ]);
  });
});

describe("CellCanvas ports that share an id across directions", () => {
  const imagePort = (direction: "input" | "output") => ({
    id: "image",
    name: "image",
    direction,
    rowOffset: 2,
    artifactTypeId: "image.raster",
    shape: "one" as const,
  });
  const operator = (
    id: string,
    col: number,
    ports: ReturnType<typeof imagePort>[],
  ) => ({
    id,
    title: id,
    subtitle: "",
    kind: "operator" as const,
    col,
    row: 2,
    widthCells: 10,
    heightCells: 6,
    ports,
  });
  const cards = [
    operator("source", 0, [imagePort("output")]),
    operator("editor", 16, [imagePort("input"), imagePort("output")]),
    operator("sink", 32, [imagePort("input")]),
  ];
  const surfaces: Record<string, CellCardSurfaceData> = {
    source: { kind: "operator", configFields: [] },
    editor: { kind: "operator", configFields: [] },
    sink: { kind: "operator", configFields: [] },
  };
  const pipeInto = {
    id: "into",
    sourceCardId: "source",
    sourcePortId: "image",
    targetCardId: "editor",
    targetPortId: "image",
  };
  const pipeOut = {
    id: "out",
    sourceCardId: "editor",
    sourcePortId: "image",
    targetCardId: "sink",
    targetPortId: "image",
  };
  const editorPort = (container: HTMLElement, direction: string) =>
    container.querySelector<HTMLElement>(
      `[data-port-card-id="editor"][data-port-direction="${direction}"]`,
    );

  afterEach(() => vi.restoreAllMocks());

  it("renders both ports with unique keys and tracks each side's pipe apart", () => {
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    const { container, render } = mountCanvas({
      graph: { cards, pipes: [pipeInto] },
      surfaceById: surfaces,
    });
    expect(
      errors.mock.calls.some((call) => String(call[0]).includes("same key")),
    ).toBe(false);
    expect(
      container.querySelectorAll('[data-port-card-id="editor"]'),
    ).toHaveLength(2);
    expect(editorPort(container, "input")?.dataset.portConnected).toBe("true");
    expect(editorPort(container, "output")?.dataset.portConnected).toBe(
      "false",
    );

    render({ graph: { cards, pipes: [pipeOut] }, surfaceById: surfaces });
    expect(editorPort(container, "input")?.dataset.portConnected).toBe("false");
    expect(editorPort(container, "output")?.dataset.portConnected).toBe("true");
    // Both pipes route: one into the left side, one out of the right.
    render({
      graph: { cards, pipes: [pipeInto, pipeOut] },
      surfaceById: surfaces,
    });
    expect(editorPort(container, "input")?.dataset.portConnected).toBe("true");
    expect(editorPort(container, "output")?.dataset.portConnected).toBe("true");
    expect(
      errors.mock.calls.some((call) => String(call[0]).includes("same key")),
    ).toBe(false);
  });
});

describe("CellCanvas stack transitions", () => {
  const artifactCard = (id: string, col: number, row: number) => ({
    id,
    title: "PNG image",
    subtitle: "",
    kind: "artifact" as const,
    col,
    row,
    widthCells: 10,
    heightCells: 8,
    resizable: true,
    ports: [],
  });
  const image = (itemCount = 1): CellCardSurfaceData => ({
    kind: "artifact",
    previewKind: "image",
    artifactTypeId: "file.png",
    typeLabel: "PNG image",
    imageUrl: "https://example.test/top.png",
    ...(itemCount > 1
      ? {
          itemCount,
          stackImageUrls: ["https://example.test/2.png"],
          stackItems: Array.from({ length: itemCount }, (_, index) => ({
            artifactId: `item-${index}`,
            label: `#${index + 1}`,
          })),
        }
      : {}),
  });

  let frames: FrameRequestCallback[] = [];
  let now = 1000;
  function enableMotion() {
    frames = [];
    now = 1000;
    vi.spyOn(performance, "now").mockImplementation(() => now);
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => {
      frames.push(cb);
      return frames.length;
    });
    vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => {});
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      writable: true,
      value: vi.fn().mockReturnValue({ matches: false }),
    });
  }
  /** Runs every pending frame well after any spring has landed. */
  function flushFrames() {
    for (let round = 0; round < 10 && frames.length > 0; round += 1) {
      now += 2000;
      const pending = frames;
      frames = [];
      React.act(() => {
        for (const frame of pending) frame(now);
      });
    }
  }

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    delete (window as unknown as { matchMedia?: unknown }).matchMedia;
  });

  function worldToClient(container: HTMLElement) {
    const viewport = container.querySelector<HTMLElement>(
      '[data-cell-viewport="true"]',
    );
    const match =
      /translate3d\((-?[\d.]+)px, (-?[\d.]+)px, 0\) scale\(([\d.]+)\)/.exec(
        viewport?.style.transform ?? "",
      );
    const [vx, vy, zoom] = [
      Number(match![1]),
      Number(match![2]),
      Number(match![3]),
    ];
    return (x: number, y: number) => ({
      clientX: vx + x * zoom,
      clientY: vy + y * zoom,
    });
  }

  const graph: CellGraph = {
    cards: [artifactCard("stack", 12, 2), artifactCard("loose", 40, 2)],
    pipes: [],
  };

  for (const stackStyle of ["fan", "deck"] as const) {
    it(`lifts the target, readies the held card and tucks it under on drop (${stackStyle})`, () => {
      enableMotion();
      const onMergeArtifactCards = vi.fn();
      const { container } = mountCanvas({
        graph,
        surfaceById: { stack: image(3), loose: image() },
        look: { ...DEFAULT_CELL_GLASS_LOOK, stackStyle },
        canMergeArtifactCards: (source, target) =>
          source === "loose" && target === "stack",
        onMergeArtifactCards,
      });
      const canvas = container.querySelector<HTMLElement>(
        '[data-cell-canvas="true"]',
      );
      canvas!.getBoundingClientRect = () => new DOMRect(0, 0, 1000, 600);
      const toClient = worldToClient(container);
      const header = container.querySelector<HTMLElement>(
        '[data-card-id="loose"] [data-card-header="true"]',
      );
      React.act(() => {
        header!.dispatchEvent(
          new PointerEvent("pointerdown", {
            bubbles: true,
            button: 0,
            pointerId: 3,
            ...toClient(1050, 60),
          }),
        );
      });
      React.act(() => {
        window.dispatchEvent(
          new PointerEvent("pointermove", {
            bubbles: true,
            pointerId: 3,
            ...toClient(400, 120),
          }),
        );
      });
      const stackCard = () =>
        container.querySelector<HTMLElement>('[data-card-id="stack"]');
      const looseCard = () =>
        container.querySelector<HTMLElement>('[data-card-id="loose"]');
      expect(stackCard()?.dataset.mergeHover).toBe("true");
      expect(stackCard()?.dataset.stackStyle).toBe(stackStyle);
      expect(looseCard()?.dataset.merging).toBe("true");

      React.act(() => {
        window.dispatchEvent(
          new PointerEvent("pointerup", {
            bubbles: true,
            pointerId: 3,
            ...toClient(400, 120),
          }),
        );
      });
      expect(onMergeArtifactCards).toHaveBeenCalledWith(
        "loose",
        "stack",
        "target-first",
      );
      expect(stackCard()?.dataset.mergeHover).toBe("false");
      // The dropped card is drawn as its tuck until it lands under the stack.
      const tuck = container.querySelector<HTMLElement>(
        '[data-stack-tuck="loose"]',
      );
      expect(tuck).not.toBeNull();
      expect(tuck!.dataset.stackTuckStyle).toBe(stackStyle);
      expect(tuck!.dataset.stackTuckSlot).toBe("1");
      expect(looseCard()).toBeNull();
      flushFrames();
      expect(container.querySelector("[data-stack-tuck]")).toBeNull();
    });
  }

  it("draws no tuck when motion is reduced", () => {
    const onMergeArtifactCardRun = vi.fn();
    const { container } = mountCanvas({
      graph: {
        cards: [artifactCard("a", 2, 2), artifactCard("b", 12, 2)],
        pipes: [],
      },
      surfaceById: { a: image(), b: image() },
      canMergeArtifactCards: () => true,
      onMergeArtifactCards: () => {},
      onMergeArtifactCardRun,
    });
    React.act(() =>
      container
        .querySelector<HTMLElement>("[data-artifact-merge-button]")!
        .click(),
    );
    expect(onMergeArtifactCardRun).toHaveBeenCalledWith(["a", "b"], "a");
    expect(container.querySelector("[data-stack-tuck]")).toBeNull();
  });

  it("glides a flush run's later cards under its first on Stack N", () => {
    enableMotion();
    const onMergeArtifactCardRun = vi.fn();
    const { container } = mountCanvas({
      graph: {
        cards: [
          artifactCard("a", 2, 2),
          artifactCard("b", 12, 2),
          artifactCard("c", 22, 2),
        ],
        pipes: [],
      },
      surfaceById: { a: image(), b: image(), c: image() },
      look: { ...DEFAULT_CELL_GLASS_LOOK, stackStyle: "deck" },
      canMergeArtifactCards: () => true,
      onMergeArtifactCards: () => {},
      onMergeArtifactCardRun,
    });
    React.act(() =>
      container
        .querySelector<HTMLElement>("[data-artifact-merge-button]")!
        .click(),
    );
    expect(onMergeArtifactCardRun).toHaveBeenCalledWith(["a", "b", "c"], "a");
    const tucks = [
      ...container.querySelectorAll<HTMLElement>("[data-stack-tuck]"),
    ];
    expect(tucks.map((tuck) => tuck.dataset.stackTuck)).toEqual(["b", "c"]);
    expect(tucks.map((tuck) => tuck.dataset.stackTuckSlot)).toEqual(["1", "2"]);
    // They start where they stood and land on the anchor's back slots.
    expect(tucks[0]!.style.transform).toContain(
      `translate3d(${12 * 25 + 4}px, ${2 * 25 + 26}px, 0)`,
    );
    expect(container.querySelector('[data-card-id="b"]')).toBeNull();
    expect(container.querySelector('[data-card-id="a"]')).not.toBeNull();
    flushFrames();
    expect(container.querySelector("[data-stack-tuck]")).toBeNull();
  });

  it("swings a new back out, rebounds the plate, and folds a leaving back away", () => {
    enableMotion();
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const stackGraph: CellGraph = {
      cards: [artifactCard("stack", 12, 2)],
      pipes: [],
    };
    const { container, render } = mountCanvas({
      graph: stackGraph,
      surfaceById: { stack: image() },
    });
    const back = () =>
      container.querySelector<HTMLElement>("[data-artifact-stack-back]");
    const stackCard = () =>
      container.querySelector<HTMLElement>('[data-card-id="stack"]');
    expect(back()).toBeNull();

    render({ graph: stackGraph, surfaceById: { stack: image(2) } });
    expect(back()?.dataset.stackBackState).toBe("entering");
    expect(stackCard()?.dataset.stackRebound).toBe("true");
    React.act(() => vi.advanceTimersByTime(400));
    expect(stackCard()?.dataset.stackRebound).toBe("false");

    // 2 -> 1: the back stays a moment, folding back under the plate.
    render({ graph: stackGraph, surfaceById: { stack: image() } });
    expect(back()?.dataset.stackBackState).toBe("exiting");
    React.act(() => vi.advanceTimersByTime(200));
    expect(back()).toBeNull();
  });

  it("drops a leaving back at once when motion is reduced", () => {
    const stackGraph: CellGraph = {
      cards: [artifactCard("stack", 12, 2)],
      pipes: [],
    };
    const { container, render } = mountCanvas({
      graph: stackGraph,
      surfaceById: { stack: image(2) },
    });
    expect(
      container.querySelector("[data-artifact-stack-back]"),
    ).not.toBeNull();
    render({ graph: stackGraph, surfaceById: { stack: image() } });
    expect(container.querySelector("[data-artifact-stack-back]")).toBeNull();
  });
});
