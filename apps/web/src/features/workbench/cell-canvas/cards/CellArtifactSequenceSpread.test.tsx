// @vitest-environment jsdom

import * as React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  computeSequenceSpreadLayout,
  type OpenSequenceSpreadLayout,
} from "../cell-artifact-stacking";
import type { ArtifactCardSurfaceData } from "../cell-contracts";
import { CELL_SIZE, type CellCardModel } from "../cell-model";
import {
  CellArtifactSequenceSpread,
  STACK_HOVER_STEP_MS,
  reorderDropIndex,
  visualSlotForSibling,
} from "./CellArtifactSequenceSpread";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const roots = new Map<Root, HTMLElement>();

afterEach(() => {
  for (const [root, container] of roots) {
    React.act(() => root.unmount());
    container.remove();
  }
  roots.clear();
  document.body.innerHTML = "";
  delete (window as unknown as { matchMedia?: unknown }).matchMedia;
  vi.restoreAllMocks();
});

const CARD: CellCardModel = {
  id: "pages",
  title: "PNG image",
  subtitle: "",
  kind: "artifact",
  col: 40,
  row: 4,
  widthCells: 10,
  heightCells: 8,
  ports: [],
};

function surface(count: number): ArtifactCardSurfaceData {
  return {
    kind: "artifact",
    previewKind: "image",
    artifactTypeId: "file.png",
    typeLabel: "PNG image",
    itemCount: count,
    stackItems: Array.from({ length: count }, (_, index) => ({
      artifactId: `a${index}`,
      imageUrl: index % 2 ? null : `https://example.test/${index}.png`,
      label: `page-${index + 1}.png`,
    })),
  };
}

function open(
  count: number,
  preferredVisibleCount?: number,
): OpenSequenceSpreadLayout {
  const layout = computeSequenceSpreadLayout({
    card: CARD,
    itemCount: count,
    foregroundCards: [CARD],
    preferredVisibleCount,
  });
  if (!layout.canExpand) throw new Error("expected an open spread");
  return layout;
}

type SpreadProps = React.ComponentProps<typeof CellArtifactSequenceSpread>;

function mount(count: number, props: Partial<SpreadProps> = {}) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  roots.set(root, container);
  const handlers = {
    onClose: vi.fn(),
    onMove: vi.fn(),
    onReorder: vi.fn(),
    onExtract: vi.fn(),
    onRemoveItem: vi.fn(),
    onInspect: vi.fn(),
    onPreferredVisibleCountChange: vi.fn(),
    onWindowStartChange: vi.fn(),
  };
  const render = (next: Partial<SpreadProps> = props) => {
    React.act(() => {
      root.render(
        <CellArtifactSequenceSpread
          card={CARD}
          surface={surface(count)}
          layout={open(count)}
          foregroundCards={[CARD]}
          // The tests speak in world units: one client pixel is one unit.
          screenToWorld={(x, y) => ({ x, y })}
          {...handlers}
          {...next}
        />,
      );
    });
  };
  render(props);
  return { container, handlers, render };
}

const q = (container: HTMLElement, selector: string) =>
  container.querySelector<HTMLElement>(selector);
const all = (container: HTMLElement, selector: string) => [
  ...container.querySelectorAll<HTMLElement>(selector),
];
const shownItems = (container: HTMLElement) =>
  all(container, "[data-sequence-item]").map((item) =>
    Number(item.dataset.sequenceItem),
  );

function pointer(
  type: string,
  target: EventTarget,
  x: number,
  y: number,
  init: PointerEventInit = {},
) {
  React.act(() => {
    target.dispatchEvent(
      new PointerEvent(type, {
        bubbles: true,
        button: 0,
        pointerId: 7,
        clientX: x,
        clientY: y,
        ...init,
      }),
    );
  });
}

/** The middle of slot `slot`'s plate in world units. */
function slotMiddle(layout: OpenSequenceSpreadLayout, slot: number) {
  return {
    x: (layout.startCol + slot * CARD.widthCells + 5) * CELL_SIZE,
    y: (CARD.row + 4) * CELL_SIZE,
  };
}

describe("reorderDropIndex", () => {
  it("lands the held card exactly in the slot it is dropped on", () => {
    expect(reorderDropIndex(0, 2)).toBe(2);
    // The window stepped mid-drag: the slot still names the final index.
    expect(reorderDropIndex(2, 2)).toBe(4);
  });
});

describe("visualSlotForSibling", () => {
  it("parts the row around a card held from inside the window", () => {
    // [0][1*][2][3]: 1 held over slot 3 -> 2 and 3 slide left.
    expect(visualSlotForSibling(2, 1, "reorder", 3, 0, 4)).toBe(1);
    expect(visualSlotForSibling(3, 1, "reorder", 3, 0, 4)).toBe(2);
    expect(visualSlotForSibling(0, 1, "reorder", 3, 0, 4)).toBe(0);
  });

  it("parts the row for a card that stepped into a side stack mid-drag", () => {
    // Held index 1, window 2..5, hovering slot 2: slots 1..2 slide left.
    expect(visualSlotForSibling(1, 1, "reorder", 2, 2, 4)).toBe(0);
    expect(visualSlotForSibling(2, 1, "reorder", 2, 2, 4)).toBe(1);
    expect(visualSlotForSibling(3, 1, "reorder", 2, 2, 4)).toBe(3);
    // Held index 9 past the window 0..3, hovering slot 1: slots 1..3 slide right.
    expect(visualSlotForSibling(0, 9, "reorder", 1, 0, 4)).toBe(0);
    expect(visualSlotForSibling(1, 9, "reorder", 1, 0, 4)).toBe(2);
    expect(visualSlotForSibling(2, 9, "reorder", 1, 0, 4)).toBe(3);
  });

  it("leaves siblings in place outside reorder", () => {
    expect(visualSlotForSibling(2, 1, "right", 3, 0, 4)).toBe(2);
  });
});

describe("CellArtifactSequenceSpread", () => {
  it("lays a short sequence open in full, flush rightward from card.col", () => {
    const { container } = mount(3);
    expect(shownItems(container)).toEqual([0, 1, 2]);
    const root = q(container, '[data-artifact-sequence-spread="pages"]');
    expect(root?.dataset.sequenceWindowed).toBe("false");
    expect(root?.style.left).toBe(`${40 * CELL_SIZE}px`);
    expect(root?.style.width).toBe(`${30 * CELL_SIZE}px`);
    const lefts = all(container, "[data-sequence-item]").map(
      (item) => item.style.left,
    );
    expect(lefts).toEqual([
      "0px",
      `${10 * CELL_SIZE}px`,
      `${20 * CELL_SIZE}px`,
    ]);
    expect(all(container, "[data-sequence-item]")[0]?.style.width).toBe(
      `${10 * CELL_SIZE}px`,
    );
    // Real headers: the type on the left, the file name on the right.
    const first = all(container, "[data-sequence-item]")[0]!;
    expect(q(first, "[data-card-title]")?.textContent).toBe("PNG image");
    expect(q(first, "[data-card-meta]")?.textContent).toBe("page-1.png");
    expect(q(first, "img")?.getAttribute("src")).toBe(
      "https://example.test/0.png",
    );
    expect(q(container, "[data-sequence-stack]")).toBeNull();
    expect(q(container, "[data-sequence-pager]")).toBeNull();
    // Collapse pill sits on the top dashed border; no order badges or scissors.
    expect(q(container, '[data-sequence-collapse="true"]')).not.toBeNull();
    expect(container.textContent).not.toContain("#1");
    expect(q(container, "[data-sequence-split]")).toBeNull();
  });

  it("steps [1][2][3][4*] -> [2*][3][4][5*] -> [3*][4][5][6] with zero empty docks", () => {
    const { container, handlers } = mount(6);
    const root = q(container, '[data-artifact-sequence-spread="pages"]')!;
    // Anchored at card.col (40), 4 slots wide = 40 cells.
    expect(root.style.left).toBe(`${40 * CELL_SIZE}px`);
    expect(root.style.width).toBe(`${40 * CELL_SIZE}px`);

    // Step 0: [1][2][3][4*] — no left stack, right stack holds 4..6 (3 items).
    expect(q(container, "[data-sequence-range]")?.textContent).toBe("1–4 / 6");
    expect(q(container, '[data-sequence-stack="left"]')).toBeNull();
    expect(shownItems(container)).toEqual([0, 1, 2]);
    const right0 = q(container, '[data-sequence-stack="right"]')!;
    expect(right0.dataset.sequenceStackCount).toBe("3");
    expect(right0.dataset.sequenceStackTop).toBe("a3");
    expect(q(right0, "[data-card-meta]")?.textContent).toBe("4–6");

    // Step 1: [2*][3][4][5*] — left stack holds 1..2 (2 items), right holds 5..6 (2 items).
    const next = q(container, '[data-sequence-step="1"]')!;
    React.act(() => next.click());
    expect(handlers.onWindowStartChange).toHaveBeenLastCalledWith(1);
    expect(q(container, "[data-sequence-range]")?.textContent).toBe("2–5 / 6");
    const left1 = q(container, '[data-sequence-stack="left"]')!;
    const right1 = q(container, '[data-sequence-stack="right"]')!;
    expect(left1.dataset.sequenceStackCount).toBe("2");
    expect(left1.dataset.sequenceStackTop).toBe("a1");
    expect(q(left1, "[data-card-meta]")?.textContent).toBe("1–2");
    expect(shownItems(container)).toEqual([2, 3]);
    expect(right1.dataset.sequenceStackCount).toBe("2");
    expect(right1.dataset.sequenceStackTop).toBe("a4");
    expect(q(right1, "[data-card-meta]")?.textContent).toBe("5–6");

    // Step 2 (end): [3*][4][5][6] — left stack holds 1..3 (3 items), no right stack.
    React.act(() => next.click());
    expect(q(container, "[data-sequence-range]")?.textContent).toBe("3–6 / 6");
    const left2 = q(container, '[data-sequence-stack="left"]')!;
    expect(left2.dataset.sequenceStackCount).toBe("3");
    expect(left2.dataset.sequenceStackTop).toBe("a2");
    expect(q(left2, "[data-card-meta]")?.textContent).toBe("1–3");
    expect(shownItems(container)).toEqual([3, 4, 5]);
    expect(q(container, '[data-sequence-stack="right"]')).toBeNull();

    // Clicking the left stack steps back by 1; ArrowRight steps forward by 1.
    React.act(() => left2.click());
    expect(q(container, "[data-sequence-range]")?.textContent).toBe("2–5 / 6");
    React.act(() => {
      root.dispatchEvent(
        new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }),
      );
    });
    expect(q(container, "[data-sequence-range]")?.textContent).toBe("3–6 / 6");
  });

  it("animates expand, step, and collapse with spring settles when motion is enabled", () => {
    const callbacks: FrameRequestCallback[] = [];
    let now = 1000;
    vi.spyOn(performance, "now").mockImplementation(() => now);
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => {
      callbacks.push(cb);
      return callbacks.length;
    });
    vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => {});
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      writable: true,
      value: vi.fn().mockReturnValue({ matches: false }),
    });

    const flushSettle = () => {
      now += 2000;
      const nextCb = callbacks.pop();
      React.act(() => {
        nextCb?.(now);
      });
    };

    const { container, handlers } = mount(6);
    // On expand mount, cards past slot 0 start from x = 0 and schedule rAF.
    expect(callbacks.length).toBe(1);
    const second = q(container, '[data-sequence-item="1"]')!;
    expect(second.style.transform).toContain("translate3d(-250px");
    flushSettle();
    expect(second.style.transform).toBe("");

    // Stepping forward queues a fresh spring transition gliding cards left by 1 card width.
    const countBeforeStep = callbacks.length;
    React.act(() => q(container, '[data-sequence-step="1"]')!.click());
    expect(callbacks.length).toBeGreaterThan(countBeforeStep);
    expect(q(container, '[data-sequence-item="2"]')?.style.transform).toContain(
      "translate3d(250px",
    );
    flushSettle();

    // Clicking Stack from windowStart = 1 first rewinds back to slot 0 (card 1),
    // then folds all cards to x = 0 and closes once settled.
    React.act(() => q(container, '[data-sequence-collapse="true"]')!.click());
    expect(handlers.onClose).not.toHaveBeenCalled();
    expect(q(container, "[data-sequence-range]")?.textContent).toBe("1–4 / 6");
    flushSettle();
    // Rewind finished and handed straight off to fold; still open until fold lands.
    expect(handlers.onClose).not.toHaveBeenCalled();
    flushSettle();
    expect(handlers.onClose).toHaveBeenCalledTimes(1);
  });

  function animateFrames() {
    const callbacks: FrameRequestCallback[] = [];
    let now = 1000;
    vi.spyOn(performance, "now").mockImplementation(() => now);
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => {
      callbacks.push(cb);
      return callbacks.length;
    });
    vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => {});
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      writable: true,
      value: vi.fn().mockReturnValue({ matches: false }),
    });
    /** Runs the pending frame `ms` later. */
    return (ms: number) => {
      now += ms;
      const next = callbacks.pop();
      React.act(() => next?.(now));
    };
  }
  const translateX = (element: HTMLElement) =>
    Number(/translate3d\((-?[\d.]+)px/.exec(element.style.transform)?.[1] ?? 0);

  it("keeps the covered slot-0 card underneath while the next card glides onto it", () => {
    const frame = animateFrames();
    const { container } = mount(6);
    frame(2000);
    // [1][2][3][4*] -> [2*][3][4][5*], then again -> [3*][4][5][6].
    React.act(() => q(container, '[data-sequence-step="1"]')!.click());
    frame(2000);
    React.act(() => q(container, '[data-sequence-step="1"]')!.click());

    const under = q(container, '[data-sequence-under-card="left"]')!;
    expect(under.getAttribute("aria-hidden")).toBe("true");
    expect(under.dataset.sequenceUnderCardTop).toBe("a1");
    expect(under.style.left).toBe("0px");
    expect(under.style.transform).toBe("");
    expect(under.style.zIndex).toBe("1");
    // The old [2*] stack keeps its backs where it stood.
    expect(all(under, "[data-artifact-stack-back]").length).toBe(1);

    const incoming = q(container, '[data-sequence-stack="left"]')!;
    expect(incoming.dataset.sequenceStackTop).toBe("a2");
    expect(incoming.style.zIndex).toBe("4");
    expect(translateX(incoming)).toBe(250);
    // Its own backs wait for it to land instead of sweeping across slot 1.
    expect(all(incoming, "[data-artifact-stack-back]")).toHaveLength(0);

    frame(16);
    const midway = translateX(q(container, '[data-sequence-stack="left"]')!);
    expect(midway).toBeGreaterThan(0);
    expect(midway).toBeLessThan(250);
    expect(q(container, '[data-sequence-under-card="left"]')).not.toBeNull();

    frame(2000);
    expect(q(container, "[data-sequence-under-card]")).toBeNull();
    const landed = q(container, '[data-sequence-stack="left"]')!;
    expect(landed.style.zIndex).toBe("2");
    expect(landed.style.transform).toBe("");
    expect(all(landed, "[data-artifact-stack-back]")).toHaveLength(2);
  });

  it("keeps the covered last-slot card underneath while the previous card glides onto it", () => {
    const frame = animateFrames();
    const { container } = mount(6);
    frame(2000);
    React.act(() => q(container, '[data-sequence-step="1"]')!.click());
    frame(2000);
    // [2*][3][4][5*] -> [1][2][3][4*].
    React.act(() => q(container, '[data-sequence-step="-1"]')!.click());

    const under = q(container, '[data-sequence-under-card="right"]')!;
    expect(under.getAttribute("aria-hidden")).toBe("true");
    expect(under.dataset.sequenceUnderCardTop).toBe("a4");
    expect(under.style.left).toBe(`${3 * 250}px`);
    expect(under.style.transform).toBe("");
    expect(under.style.zIndex).toBe("1");

    const incoming = q(container, '[data-sequence-stack="right"]')!;
    expect(incoming.dataset.sequenceStackTop).toBe("a3");
    expect(incoming.style.zIndex).toBe("4");
    expect(translateX(incoming)).toBe(-250);
    expect(all(under, "[data-artifact-stack-back]")).toHaveLength(1);
    expect(all(incoming, "[data-artifact-stack-back]")).toHaveLength(0);

    frame(2000);
    expect(q(container, "[data-sequence-under-card]")).toBeNull();
    const landed = q(container, '[data-sequence-stack="right"]')!;
    expect(landed.style.zIndex).toBe("2");
    expect(landed.style.transform).toBe("");
    expect(all(landed, "[data-artifact-stack-back]")).toHaveLength(2);
  });

  it("replaces the under-card when a step reverses mid-flight, and drops it on collapse", () => {
    const frame = animateFrames();
    const { container } = mount(6);
    frame(2000);
    React.act(() => q(container, '[data-sequence-step="1"]')!.click());
    frame(2000);
    React.act(() => q(container, '[data-sequence-step="1"]')!.click());
    frame(16);
    React.act(() => q(container, '[data-sequence-step="-1"]')!.click());
    expect(all(container, "[data-sequence-under-card]")).toHaveLength(1);
    const under = q(container, '[data-sequence-under-card="right"]')!;
    expect(under.dataset.sequenceUnderCardTop).toBe("a5");

    // Collapsing from windowStart = 1 rewinds through the carousel under-card,
    // then drops it when folding into slot 0.
    React.act(() => q(container, '[data-sequence-collapse="true"]')!.click());
    expect(
      q(container, '[data-sequence-under-card="right"]')?.dataset
        .sequenceUnderCardTop,
    ).toBe("a4");
    frame(2000);
    expect(q(container, "[data-sequence-under-card]")).toBeNull();
  });

  it("draws no under-card when motion is reduced", () => {
    const { container } = mount(6);
    React.act(() => q(container, '[data-sequence-step="1"]')!.click());
    expect(q(container, "[data-sequence-under-card]")).toBeNull();
  });

  it("reorders an open card in whole card-width steps while shifting siblings", () => {
    const layout = open(3);
    const { container, handlers } = mount(3);
    const first = all(container, "[data-sequence-item]")[0]!;
    const start = slotMiddle(layout, 0);
    pointer("pointerdown", first, start.x, start.y);
    const past = slotMiddle(layout, 2);
    pointer("pointermove", window, past.x + 20, past.y);
    expect(
      q(container, '[data-sequence-item="0"]')?.dataset.sequenceLifted,
    ).toBe("true");
    expect(
      q(container, '[data-sequence-item="0"]')?.dataset.sequenceTargetSlot,
    ).toBe("2");
    expect(
      q(container, '[data-sequence-item="1"]')?.dataset.sequenceVisualSlot,
    ).toBe("0");
    expect(
      q(container, '[data-sequence-item="2"]')?.dataset.sequenceVisualSlot,
    ).toBe("1");
    pointer("pointerup", window, past.x + 20, past.y);
    expect(handlers.onReorder).toHaveBeenCalledWith("pages", 0, 2);
    expect(handlers.onExtract).not.toHaveBeenCalled();
    expect(q(container, "[data-sequence-lifted]")).toBeNull();
  });

  it("steps reorder slots by the card's current width in cells", () => {
    const wideCard: CellCardModel = { ...CARD, widthCells: 14 };
    const wideLayout = computeSequenceSpreadLayout({
      card: wideCard,
      itemCount: 3,
      foregroundCards: [wideCard],
    });
    if (!wideLayout.canExpand) throw new Error("expected open wide spread");
    const { container, handlers } = mount(3, {
      card: wideCard,
      layout: wideLayout,
      foregroundCards: [wideCard],
    });
    const first = all(container, "[data-sequence-item]")[0]!;
    const startX = (wideLayout.startCol + 7) * CELL_SIZE;
    const startY = (wideCard.row + 4) * CELL_SIZE;
    pointer("pointerdown", first, startX, startY);
    pointer("pointermove", window, startX + 6 * CELL_SIZE, startY);
    expect(
      q(container, '[data-sequence-item="0"]')?.dataset.sequenceTargetSlot,
    ).toBe("0");
    pointer("pointermove", window, startX + 8 * CELL_SIZE, startY);
    expect(
      q(container, '[data-sequence-item="0"]')?.dataset.sequenceTargetSlot,
    ).toBe("1");
    expect(
      q(container, '[data-sequence-item="1"]')?.dataset.sequenceVisualSlot,
    ).toBe("0");
    pointer("pointerup", window, startX + 8 * CELL_SIZE, startY);
    expect(handlers.onReorder).toHaveBeenCalledWith("pages", 0, 1);
  });

  it("moves the spread via its top drag handle clear of other cards", () => {
    const blocker: CellCardModel = { ...CARD, id: "blocker", col: 44, row: 14 };
    const { container, handlers } = mount(3, {
      foregroundCards: [CARD, blocker],
    });
    const moveHandle = q(container, '[data-sequence-move="true"]');
    expect(moveHandle).not.toBeNull();
    pointer("pointerdown", moveHandle!, 200, 100);
    pointer("pointermove", window, 200 + 4 * CELL_SIZE, 100 + 2 * CELL_SIZE);
    expect(q(container, "[data-sequence-move-ghost]")).not.toBeNull();
    pointer("pointerup", window, 200 + 4 * CELL_SIZE, 100 + 2 * CELL_SIZE);
    expect(handlers.onMove).toHaveBeenCalledWith("pages", 44, 6);
  });

  it("moves a held card onto a side stack", () => {
    const layout = open(20);
    const { container, handlers } = mount(20);
    const next = q(container, '[data-sequence-step="1"]')!;
    for (let i = 0; i < 3; i += 1) React.act(() => next.click());
    // Step 3: [4* (slot 0)] [5 (slot 1, index 4)] [6 (slot 2, index 5)] [7* (slot 3)]
    const held = q(container, '[data-sequence-item="4"]')!;
    const start = slotMiddle(layout, 1);
    pointer("pointerdown", held, start.x, start.y);
    const overLeft = slotMiddle(layout, 0);
    pointer("pointermove", window, overLeft.x, overLeft.y);
    expect(
      q(container, '[data-sequence-stack="left"]')?.dataset.sequenceStackDrop,
    ).toBe("true");
    pointer("pointerup", window, overLeft.x, overLeft.y);
    expect(handlers.onReorder).toHaveBeenCalledWith("pages", 4, 3);
  });

  it("pulls a card out onto the canvas where it is dropped", () => {
    const layout = open(3);
    const blocker: CellCardModel = { ...CARD, id: "blocker", col: 40, row: 20 };
    const { container, handlers } = mount(3, {
      foregroundCards: [CARD, blocker],
    });
    const second = all(container, "[data-sequence-item]")[1]!;
    const start = slotMiddle(layout, 1);
    pointer("pointerdown", second, start.x, start.y);
    const drop = { x: start.x + 3 * CELL_SIZE, y: start.y + 30 * CELL_SIZE };
    pointer("pointermove", window, drop.x, drop.y);
    const landing = q(container, "[data-sequence-landing]");
    expect(landing?.dataset.sequenceLanding).toBe("53,34");
    pointer("pointerup", window, drop.x, drop.y);
    expect(handlers.onExtract).toHaveBeenCalledWith("pages", 1, {
      col: 53,
      row: 34,
    });
    expect(handlers.onReorder).not.toHaveBeenCalled();
  });

  it("lands a pulled-out card clear of the card under the drop", () => {
    const layout = open(3);
    const blocker: CellCardModel = { ...CARD, id: "blocker", col: 50, row: 30 };
    const { container, handlers } = mount(3, {
      foregroundCards: [CARD, blocker],
    });
    const first = all(container, "[data-sequence-item]")[0]!;
    const start = slotMiddle(layout, 0);
    pointer("pointerdown", first, start.x, start.y);
    const drop = { x: start.x + 10 * CELL_SIZE, y: start.y + 26 * CELL_SIZE };
    pointer("pointermove", window, drop.x, drop.y);
    const cell = q(container, "[data-sequence-landing]")!
      .dataset.sequenceLanding!.split(",")
      .map(Number);
    const [col, row] = cell as [number, number];
    const overlaps =
      col < blocker.col + blocker.widthCells &&
      blocker.col < col + CARD.widthCells &&
      row < blocker.row + blocker.heightCells &&
      blocker.row < row + CARD.heightCells;
    expect(overlaps).toBe(false);
    pointer("pointerup", window, drop.x, drop.y);
    expect(handlers.onExtract).toHaveBeenLastCalledWith("pages", 0, {
      col,
      row,
    });
  });

  it("shows an insertion bar and parts cards when an external card hovers over a slot", () => {
    const { container } = mount(3, { externalInsertSlot: 1 });
    expect(q(container, '[data-sequence-external-insert="1"]')).not.toBeNull();
    expect(q(container, '[data-sequence-item="0"]')?.style.transform).toContain(
      "-8px",
    );
    expect(q(container, '[data-sequence-item="1"]')?.style.transform).toContain(
      "8px",
    );
  });

  it("auto-steps under a held card resting on a side stack without stale sibling offsets, then lands it in the hovered slot", () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    try {
      const layout = open(6);
      const { container, handlers } = mount(6);
      // [0][1][2][3*]: hold 1, part the row over slot 2, then rest on the right stack.
      const held = q(container, '[data-sequence-item="1"]')!;
      const start = slotMiddle(layout, 1);
      pointer("pointerdown", held, start.x, start.y);
      const overSlot2 = slotMiddle(layout, 2);
      pointer("pointermove", window, overSlot2.x, overSlot2.y);
      expect(
        q(container, '[data-sequence-item="2"]')?.dataset.sequenceVisualSlot,
      ).toBe("1");
      const overRight = slotMiddle(layout, 3);
      pointer("pointermove", window, overRight.x, overRight.y);
      React.act(() => vi.advanceTimersByTime(STACK_HOVER_STEP_MS));
      expect(q(container, "[data-sequence-range]")?.textContent).toBe(
        "2–5 / 6",
      );
      // Item 2 now sits in slot 1; its old-window settle must not offset it.
      expect(q(container, '[data-sequence-item="2"]')?.style.transform).toBe(
        "",
      );
      // The held card's own index tops the left stack; the stack still shows.
      const left = q(container, '[data-sequence-stack="left"]');
      expect(left?.dataset.sequenceStackTop).toBe("a0");

      React.act(() => vi.advanceTimersByTime(STACK_HOVER_STEP_MS));
      expect(q(container, "[data-sequence-range]")?.textContent).toBe(
        "3–6 / 6",
      );
      // Back into the open row over slot 2: the held card lands exactly there.
      pointer("pointermove", window, overSlot2.x, overSlot2.y);
      expect(
        q(container, '[data-sequence-item="1"]')?.dataset.sequenceTargetSlot,
      ).toBe("2");
      expect(
        q(container, '[data-sequence-item="3"]')?.dataset.sequenceVisualSlot,
      ).toBe("0");
      expect(
        q(container, '[data-sequence-item="4"]')?.dataset.sequenceVisualSlot,
      ).toBe("1");
      pointer("pointerup", window, overSlot2.x, overSlot2.y);
      expect(handlers.onReorder).toHaveBeenCalledWith("pages", 1, 4);
    } finally {
      vi.useRealTimers();
    }
  });

  it("fans the real next pictures behind each side stack", () => {
    const { container } = mount(6);
    React.act(() => q(container, '[data-sequence-step="1"]')!.click());
    React.act(() => q(container, '[data-sequence-step="1"]')!.click());
    // [0,1,2*][3][4][5]: the left stack's backs are items 1 and 0.
    const left = q(container, '[data-sequence-stack="left"]')!;
    const backs = all(left, "[data-artifact-stack-back]");
    expect(backs).toHaveLength(2);
    const peek = (n: number) =>
      q(left, `[data-artifact-stack-back="${n}"] img`)?.getAttribute("src") ??
      null;
    // Item 1 has no picture; item 0 does.
    expect(peek(1)).toBeNull();
    expect(peek(2)).toBe("https://example.test/0.png");
  });

  it("pages with Shift on the arrow keys and on a stack's Enter", () => {
    const { container } = mount(20);
    const root = q(container, '[data-artifact-sequence-spread="pages"]')!;
    React.act(() => {
      root.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "ArrowRight",
          shiftKey: true,
          bubbles: true,
        }),
      );
    });
    // 4 open slots page by the 2 cards between the stacks.
    expect(q(container, "[data-sequence-range]")?.textContent).toBe("3–6 / 20");
    React.act(() => {
      q(container, '[data-sequence-stack="right"]')!.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "Enter",
          shiftKey: true,
          bubbles: true,
        }),
      );
    });
    expect(q(container, "[data-sequence-range]")?.textContent).toBe("5–8 / 20");
  });

  it("keeps the window in range after items go, so a later insert does not jump back", () => {
    const { container, render } = mount(6);
    const next = q(container, '[data-sequence-step="1"]')!;
    React.act(() => next.click());
    React.act(() => next.click());
    expect(q(container, "[data-sequence-range]")?.textContent).toBe("3–6 / 6");
    render({ surface: surface(5), layout: open(5, 4) });
    expect(q(container, "[data-sequence-range]")?.textContent).toBe("2–5 / 5");
    render({ surface: surface(6), layout: open(6, 4) });
    expect(q(container, "[data-sequence-range]")?.textContent).toBe("2–5 / 6");
  });

  it("draws the edge insertion bars between the frame and the slid-in plates", () => {
    const layout = open(3);
    const width = layout.totalCols * CELL_SIZE;
    const first = mount(3, { externalInsertSlot: 0 });
    expect(
      q(first.container, '[data-sequence-external-insert="0"]')?.style.left,
    ).toBe("5px");
    expect(
      q(first.container, '[data-sequence-item="2"]')?.style.transform,
    ).toContain("10px");
    const last = mount(3, { externalInsertSlot: 3 });
    expect(
      q(last.container, '[data-sequence-external-insert="3"]')?.style.left,
    ).toBe(`${width - 5}px`);
    expect(
      q(last.container, '[data-sequence-item="0"]')?.style.transform,
    ).toContain("-10px");
  });

  it("offers Inspect and Remove in an open card's menu", async () => {
    const { container, handlers } = mount(3);
    const second = all(container, "[data-sequence-item]")[1]!;
    React.act(() => second.focus());
    const trigger = q(second, '[aria-label="Actions for page-2.png"]');
    expect(trigger).not.toBeNull();
    await React.act(async () => trigger!.click());
    const items = [
      ...document.querySelectorAll<HTMLElement>('[role="menuitem"]'),
    ];
    expect(items.map((item) => item.textContent)).toEqual([
      "Inspect",
      "Remove",
    ]);
    await React.act(async () => items[1]!.click());
    expect(handlers.onRemoveItem).toHaveBeenCalledWith("pages", 1);
  });

  it("widens the open row from its right edge in whole cards", () => {
    const layout = open(20);
    const { container, handlers, render } = mount(20);
    const handle = q(container, '[data-sequence-resize="true"]');
    expect(handle).not.toBeNull();
    const x = (layout.startCol + layout.totalCols) * CELL_SIZE;
    pointer("pointerdown", handle!, x, 100);
    pointer("pointermove", handle!, x + 2 * 10 * CELL_SIZE + 10, 100);
    expect(handlers.onPreferredVisibleCountChange).toHaveBeenLastCalledWith(6);
    pointer("pointerup", handle!, x + 2 * 10 * CELL_SIZE + 10, 100);
    render({ layout: open(20, 6) });
    expect(q(container, "[data-sequence-range]")?.textContent).toBe("1–6 / 20");
  });

  it("glides revealed cards out from the old right edge when the row widens", () => {
    const frame = animateFrames();
    const layout = open(20);
    const { container, render } = mount(20);
    frame(2000); // the expand settles
    const cw = CARD.widthCells * CELL_SIZE;
    const visible = layout.visibleCount;
    const handle = q(container, '[data-sequence-resize="true"]')!;
    const x = (layout.startCol + layout.totalCols) * CELL_SIZE;
    pointer("pointerdown", handle, x, 100);
    pointer("pointermove", handle, x + cw + 10, 100);
    render({ layout: open(20, visible + 1) });
    // The card the old right stack held stays; the one past it comes out
    // from under that stack.
    const revealed = q(container, `[data-sequence-slot="${visible}"]`)!;
    expect(translateX(revealed)).toBe(-cw);
    frame(2000);
    expect(revealed.style.transform).toBe("");
    pointer("pointerup", handle, x + cw + 10, 100);
  });

  it("tucks retired cards under the new right stack when the row narrows", () => {
    const frame = animateFrames();
    const layout = open(20, 6);
    const { container, render } = mount(20, { layout });
    frame(2000);
    const cw = CARD.widthCells * CELL_SIZE;
    const handle = q(container, '[data-sequence-resize="true"]')!;
    const x = (layout.startCol + layout.totalCols) * CELL_SIZE;
    pointer("pointerdown", handle, x, 100);
    pointer("pointermove", handle, x - 2 * cw - 10, 100);
    render({ layout: open(20, 4) });
    const tucks = all(container, "[data-sequence-resize-tuck]");
    // Old slots 4 and 5 (items 4, 5) glide in under the new last slot (3).
    expect(tucks.map((tuck) => tuck.dataset.sequenceResizeTuck)).toEqual([
      "a4",
      "a5",
    ]);
    for (const tuck of tucks) {
      expect(tuck.getAttribute("aria-hidden")).toBe("true");
      expect(tuck.style.zIndex).toBe("1");
      expect(tuck.style.pointerEvents).toBe("none");
    }
    expect(translateX(tucks[0]!)).toBe(4 * cw);
    expect(translateX(tucks[1]!)).toBe(5 * cw);
    frame(2000);
    expect(all(container, "[data-sequence-resize-tuck]")).toHaveLength(0);
    pointer("pointerup", handle, x - 2 * cw - 10, 100);
  });

  it("resizes with no glide when motion is reduced", () => {
    const layout = open(20, 6);
    const { container, render } = mount(20, { layout });
    const cw = CARD.widthCells * CELL_SIZE;
    const handle = q(container, '[data-sequence-resize="true"]')!;
    const x = (layout.startCol + layout.totalCols) * CELL_SIZE;
    pointer("pointerdown", handle, x, 100);
    pointer("pointermove", handle, x - 2 * cw - 10, 100);
    render({ layout: open(20, 4) });
    expect(all(container, "[data-sequence-resize-tuck]")).toHaveLength(0);
    pointer("pointerup", handle, x - 2 * cw - 10, 100);
  });

  it("draws its side stacks in the canvas's stack style", () => {
    const { container } = mount(20, { stackStyle: "deck" });
    const back = q(
      container,
      '[data-sequence-stack="right"] [data-artifact-stack-back="1"]',
    )!;
    expect(back.style.transform).toBe("translate3d(0px, 6px, 0) scale(0.96)");
    const fan = mount(20).container;
    expect(
      q(fan, '[data-sequence-stack="right"] [data-artifact-stack-back="1"]')!
        .style.transform,
    ).toContain("rotate(");
  });

  it("syncs a growing stack's plate and backs smoothly from 2 to 3 cards in both Fan and Deck", () => {
    const parseRotate = (el: HTMLElement) =>
      Number(/rotate\((-?[\d.]+)deg\)/.exec(el.style.transform)?.[1] ?? 0);
    const parseDropY = (el: HTMLElement) =>
      Number(
        /translate3d\(0px,\s*(-?[\d.]+)px/.exec(el.style.transform)?.[1] ?? 0,
      );

    // Fan: 6 items, step right to [2*][3][4][5–6], then step left to [1][2][3][4–6].
    const frameFan = animateFrames();
    const fan = mount(6);
    frameFan(2000);
    React.act(() => q(fan.container, '[data-sequence-step="1"]')!.click());
    frameFan(2000);
    React.act(() => q(fan.container, '[data-sequence-step="-1"]')!.click());

    const underStart = q(fan.container, '[data-sequence-under-card="right"]')!;
    const plateStart = q(underStart, "article")!;
    const backStart = q(underStart, '[data-artifact-stack-back="1"]')!;
    // At t = 0: under plate sits flat (0deg) and back #1 sits at rest depth 1.
    expect(plateStart.style.transform).toBe("");
    const unitDeg = parseRotate(backStart);
    expect(unitDeg).toBeLessThan(0);

    // Mid-flight: under plate rotates into (0..1) depth and back #1 rotates into (1..2).
    frameFan(60);
    const underMid = q(fan.container, '[data-sequence-under-card="right"]')!;
    const plateMidDeg = parseRotate(q(underMid, "article")!);
    const backMidDeg = parseRotate(
      q(underMid, '[data-artifact-stack-back="1"]')!,
    );
    expect(plateMidDeg).toBeLessThan(0);
    expect(plateMidDeg).toBeGreaterThan(unitDeg);
    expect(backMidDeg).toBeLessThan(unitDeg);
    expect(backMidDeg).toBeGreaterThan(unitDeg * 2);

    // Settled: landed stack holds 2 backs at rest depths 1 and 2.
    frameFan(2000);
    const landed = q(fan.container, '[data-sequence-stack="right"]')!;
    expect(
      parseRotate(q(landed, '[data-artifact-stack-back="1"]')!),
    ).toBeCloseTo(unitDeg, 2);
    expect(
      parseRotate(q(landed, '[data-artifact-stack-back="2"]')!),
    ).toBeCloseTo(unitDeg * 2, 2);

    // Deck: same transition interpolates translateY 0 -> 6 and 6 -> 12.
    const frameDeck = animateFrames();
    const deck = mount(6, { stackStyle: "deck" });
    frameDeck(2000);
    React.act(() => q(deck.container, '[data-sequence-step="1"]')!.click());
    frameDeck(2000);
    React.act(() => q(deck.container, '[data-sequence-step="-1"]')!.click());
    frameDeck(60);
    const deckUnder = q(deck.container, '[data-sequence-under-card="right"]')!;
    const deckPlateY = parseDropY(q(deckUnder, "article")!);
    const deckBackY = parseDropY(
      q(deckUnder, '[data-artifact-stack-back="1"]')!,
    );
    expect(deckPlateY).toBeGreaterThan(0);
    expect(deckPlateY).toBeLessThan(6);
    expect(deckBackY).toBeGreaterThan(6);
    expect(deckBackY).toBeLessThan(12);
  });

  it("rises an uncovered side stack smoothly when shrinking 3 -> 2 and 2 -> 1", () => {
    const parseDropY = (el: HTMLElement) =>
      Number(
        /translate3d\(0px,\s*(-?[\d.]+)px/.exec(el.style.transform)?.[1] ?? 0,
      );
    const frame = animateFrames();
    const { container } = mount(6, { stackStyle: "deck" });
    frame(2000);

    // Step -> from [1][2][3][4–6] to [2*][3][4][5–6] (right stack shrinks 3 -> 2).
    React.act(() => q(container, '[data-sequence-step="1"]')!.click());
    const rightStart = q(container, '[data-sequence-stack="right"]')!;
    // At t = 0, newly revealed #5 starts at back #1 depth (6px) and #6 at back #2 depth (12px).
    expect(parseDropY(q(rightStart, "article")!)).toBeCloseTo(6, 2);
    expect(
      parseDropY(q(rightStart, '[data-artifact-stack-back="1"]')!),
    ).toBeCloseTo(12, 2);

    frame(60);
    const rightMid = q(container, '[data-sequence-stack="right"]')!;
    expect(parseDropY(q(rightMid, "article")!)).toBeGreaterThan(0);
    expect(parseDropY(q(rightMid, "article")!)).toBeLessThan(6);
    expect(
      parseDropY(q(rightMid, '[data-artifact-stack-back="1"]')!),
    ).toBeGreaterThan(6);
    expect(
      parseDropY(q(rightMid, '[data-artifact-stack-back="1"]')!),
    ).toBeLessThan(12);

    frame(2000);
    const rightRest = q(container, '[data-sequence-stack="right"]')!;
    expect(q(rightRest, "article")!.style.transform).toBe("");
    expect(
      parseDropY(q(rightRest, '[data-artifact-stack-back="1"]')!),
    ).toBeCloseTo(6, 2);

    // Step -> again to [3*][4][5][6] (right stack shrinks 2 -> 1 into an open card).
    React.act(() => q(container, '[data-sequence-step="1"]')!.click());
    const openRightStart = q(container, '[data-sequence-item="5"]')!;
    expect(openRightStart.style.zIndex).toBe("2");
    expect(parseDropY(q(openRightStart, "article")!)).toBeCloseTo(6, 2);

    frame(60);
    const openRightMid = q(container, '[data-sequence-item="5"]')!;
    expect(parseDropY(q(openRightMid, "article")!)).toBeGreaterThan(0);
    expect(parseDropY(q(openRightMid, "article")!)).toBeLessThan(6);

    frame(2000);
    const openRightRest = q(container, '[data-sequence-item="5"]')!;
    expect(openRightRest.style.zIndex).toBe("3");
    expect(q(openRightRest, "article")!.style.transform).toBe("");
  });

  it("fades the second back out cleanly when a 3-card stack grows to 4 cards", () => {
    const frame = animateFrames();
    const { container } = mount(7, { stackStyle: "deck" });
    frame(2000);
    // [1][2][3][4–7] -> step -> [2*][3][4][5–7] (3 cards, 2 backs) -> step <- [1][2][3][4–7] (4 cards)
    React.act(() => q(container, '[data-sequence-step="1"]')!.click());
    frame(2000);
    React.act(() => q(container, '[data-sequence-step="-1"]')!.click());

    frame(60);
    const under = q(container, '[data-sequence-under-card="right"]')!;
    const back2 = q(under, '[data-artifact-stack-back="2"]')!;
    const opacity = Number(back2.style.opacity);
    expect(opacity).toBeGreaterThan(0);
    expect(opacity).toBeLessThan(1);

    frame(2000);
    expect(q(container, "[data-sequence-under-card]")).toBeNull();
  });

  it("fans a narrowed right stack's backs out in sync with the tucking card", () => {
    const parseDropY = (el: HTMLElement) =>
      Number(
        /translate3d\(0px,\s*(-?[\d.]+)px/.exec(el.style.transform)?.[1] ?? 0,
      );
    const frame = animateFrames();
    const layout = open(20, 6);
    const { container, render } = mount(20, { layout, stackStyle: "deck" });
    frame(2000);
    const cw = CARD.widthCells * CELL_SIZE;
    const handle = q(container, '[data-sequence-resize="true"]')!;
    const x = (layout.startCol + layout.totalCols) * CELL_SIZE;
    pointer("pointerdown", handle, x, 100);
    pointer("pointermove", handle, x - 2 * cw - 10, 100);
    render({ layout: open(20, 4), stackStyle: "deck" });

    // At t = 0, backs start tucked at depth 0 behind the new right stack.
    const backStart = q(
      container,
      '[data-sequence-stack="right"] [data-artifact-stack-back="1"]',
    )!;
    expect(parseDropY(backStart)).toBeCloseTo(0, 2);

    frame(60);
    const backMid = q(
      container,
      '[data-sequence-stack="right"] [data-artifact-stack-back="1"]',
    )!;
    expect(parseDropY(backMid)).toBeGreaterThan(0);
    expect(parseDropY(backMid)).toBeLessThan(6);

    frame(2000);
    const backRest = q(
      container,
      '[data-sequence-stack="right"] [data-artifact-stack-back="1"]',
    )!;
    expect(parseDropY(backRest)).toBeCloseTo(6, 2);
    pointer("pointerup", handle, x - 2 * cw - 10, 100);
  });

  it("avoids compounding drop shadows and overlapping headers on tucked cards during expand, collapse, step, and resize", () => {
    const frame = animateFrames();
    const { container, render } = mount(6);

    // Frame 0 of expand: all trailing slots start at x = 0 with shadow suppressed and header hidden.
    const slot0 = q(container, '[data-sequence-slot="0"]')!;
    const slot1 = q(container, '[data-sequence-slot="1"]')!;
    const rightSlot = q(container, '[data-sequence-stack="right"]')!;
    expect(q(slot0, "article")!.dataset.plateShadow).toBe("rest");
    expect(q(slot0, "[data-card-header]")!.style.opacity).toBe("");
    expect(q(slot1, "article")!.dataset.plateShadow).toBe("none");
    expect(q(slot1, "[data-card-header]")!.style.opacity).toBe("0");
    expect(q(rightSlot, "article")!.dataset.plateShadow).toBe("none");
    expect(q(rightSlot, "[data-card-header]")!.style.opacity).toBe("0");

    // Settled open: every slot carries its normal rest shadow and visible header.
    frame(2000);
    for (const el of all(container, "[data-sequence-slot]")) {
      expect(q(el, "article")!.dataset.plateShadow).toBe("rest");
      expect(q(el, "[data-card-header]")!.style.opacity).toBe("");
    }

    // Mid-step: under-card suppresses its own drop shadow so the gliding card carries the single shadow.
    React.act(() => q(container, '[data-sequence-step="1"]')!.click());
    const under = q(container, '[data-sequence-under-card="left"]')!;
    expect(q(under, "article")!.dataset.plateShadow).toBe("none");
    frame(2000);

    // Narrowing resize: tucking cards suppress drop shadows.
    const layout6 = open(20, 6);
    render({ layout: layout6, surface: surface(20) });
    frame(2000);
    const cw = CARD.widthCells * CELL_SIZE;
    const handle = q(container, '[data-sequence-resize="true"]')!;
    const x = (layout6.startCol + layout6.totalCols) * CELL_SIZE;
    pointer("pointerdown", handle, x, 100);
    pointer("pointermove", handle, x - 2 * cw - 10, 100);
    render({ layout: open(20, 4), surface: surface(20) });
    const tuck = q(container, "[data-sequence-resize-tuck]")!;
    expect(q(tuck, "article")!.dataset.plateShadow).toBe("none");
    pointer("pointerup", handle, x - 2 * cw - 10, 100);
    frame(2000);

    // Collapse from windowStart = 1: rewinds first (slot 0 rises without shadow
    // while covered), then folds (slot 0 holds the rest shadow while trailing
    // slots suppress theirs so closing onto slot 0 never stacks halos).
    React.act(() => q(container, '[data-sequence-collapse="true"]')!.click());
    frame(2000);
    expect(
      q(q(container, '[data-sequence-slot="0"]')!, "article")!.dataset
        .plateShadow,
    ).toBe("rest");
    expect(
      q(q(container, '[data-sequence-slot="1"]')!, "article")!.dataset
        .plateShadow,
    ).toBe("none");
    frame(2000);
  });

  it("rewinds to card 1 with synced depth & middle-card tuck before folding backs out on collapse", () => {
    const parseDropY = (el: HTMLElement) =>
      Number(
        /translate3d\(0px,\s*(-?[\d.]+)px/.exec(el.style.transform)?.[1] ?? 0,
      );
    const frame = animateFrames();
    const layout = open(5, 3);
    const { container, handlers } = mount(5, { layout, stackStyle: "deck" });
    frame(2000);

    // Step to the end: 3–5 / 5 -> [1–3][4][5].
    React.act(() => q(container, '[data-sequence-step="1"]')!.click());
    frame(2000);
    React.act(() => q(container, '[data-sequence-step="1"]')!.click());
    frame(2000);
    expect(q(container, "[data-sequence-range]")?.textContent).toBe("3–5 / 5");

    // Clicking Stack rewinds to 1–3 / 5:
    // - card 1 (a0) rises from depth 2 in slot 0,
    // - card 4 (a3) tucks smoothly from slot 1 to slot 2 instead of vanishing,
    // - card 5 (a4) stays as the sinking under-card on the right.
    React.act(() => q(container, '[data-sequence-collapse="true"]')!.click());
    expect(handlers.onClose).not.toHaveBeenCalled();
    expect(q(container, "[data-sequence-range]")?.textContent).toBe("1–3 / 5");
    const slot0Start = q(container, '[data-sequence-slot="0"]')!;
    expect(slot0Start.dataset.artifactId).toBe("a0");
    expect(parseDropY(q(slot0Start, "article")!)).toBeCloseTo(12, 2);
    const stepTuck = q(container, '[data-sequence-step-tuck="a3"]')!;
    expect(stepTuck).not.toBeNull();
    expect(translateX(stepTuck)).toBe(CARD.widthCells * CELL_SIZE);
    const under = q(container, '[data-sequence-under-card="right"]')!;
    expect(under.dataset.sequenceUnderCardTop).toBe("a4");

    // Rewind settles -> transitions straight into fold onto card 1 with backs
    // starting at 0 depth and fanning out in sync as cards 2 and 3 tuck under.
    frame(2000);
    expect(handlers.onClose).not.toHaveBeenCalled();
    expect(q(container, "[data-sequence-under-card]")).toBeNull();
    expect(q(container, "[data-sequence-step-tuck]")).toBeNull();
    const slot0FoldStart = q(container, '[data-sequence-slot="0"]')!;
    const backsStart = all(slot0FoldStart, "[data-artifact-stack-back]");
    expect(backsStart).toHaveLength(2);
    expect(parseDropY(backsStart[0]!)).toBeCloseTo(0, 2);

    // Mid-fold: backs fan partway out while trailing cards glide to x = 0.
    frame(60);
    const slot0FoldMid = q(container, '[data-sequence-slot="0"]')!;
    const back1MidY = parseDropY(
      q(slot0FoldMid, '[data-artifact-stack-back="1"]')!,
    );
    const back2MidY = parseDropY(
      q(slot0FoldMid, '[data-artifact-stack-back="2"]')!,
    );
    expect(back1MidY).toBeGreaterThan(0);
    expect(back1MidY).toBeLessThan(6);
    expect(back2MidY).toBeGreaterThan(back1MidY);
    expect(back2MidY).toBeLessThan(12);

    // Fold settles -> closes cleanly once card 1's backs reach rest depth.
    frame(2000);
    expect(handlers.onClose).toHaveBeenCalledTimes(1);
  });

  it("closes on Escape and via the Stack button", () => {
    const { container, handlers } = mount(3);
    React.act(() => {
      q(container, "[data-artifact-sequence-spread]")!.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
      );
    });
    expect(handlers.onClose).toHaveBeenCalledTimes(1);
    React.act(() => {
      q(container, '[data-sequence-collapse="true"]')!.click();
    });
    expect(handlers.onClose).toHaveBeenCalledTimes(2);
  });
});
