import { describe, expect, it, vi } from "vitest";

import type { CellRemotePeerState } from "./cell-contracts";
import type { CellCardModel, RoutedCellPipe, WorldPoint } from "./cell-model";
import {
  EMPTY_REMOTE_BADGES,
  cardsInMarqueeRect,
  createCellInteractionStore,
  normalizeMarqueeRect,
  pipesInMarqueeRect,
} from "./cell-store";

describe("cell interaction store", () => {
  it("publishes selection changes only to changed IDs and preserves equal snapshots", () => {
    const store = createCellInteractionStore();
    const a = vi.fn(() => store.getCardState("a").selected);
    const c = vi.fn(() => store.getCardState("c").selected);
    const pipe = vi.fn(() => store.getPipeState("pipe").selected);
    const selection = vi.fn();
    store.subscribeCard("a", a);
    store.subscribeCard("c", c);
    store.subscribePipe("pipe", pipe);
    store.subscribeSelection(selection);
    const untouchedCard = store.getCardState("c");

    store.setSelection({ cardIds: ["a", "b"], pipeIds: ["pipe"] });
    expect(a).toHaveLastReturnedWith(true);
    expect(pipe).toHaveLastReturnedWith(true);
    const previousSelection = store.getSelection();
    const selectedCard = store.getCardState("a");
    const selectedPipe = store.getPipeState("pipe");

    store.setSelection({ cardIds: ["b", "a", "a"] });
    expect(store.getSelection()).toBe(previousSelection);
    expect(store.getCardState("a")).toBe(selectedCard);
    expect(store.getPipeState("pipe")).toBe(selectedPipe);
    expect(selection).toHaveBeenCalledTimes(1);

    store.toggleCardSelection("a");
    expect(store.getSelection()).toEqual({
      cardIds: new Set(["b"]),
      pipeIds: new Set(["pipe"]),
    });
    expect(previousSelection.cardIds).toEqual(new Set(["a", "b"]));
    expect(a).toHaveLastReturnedWith(false);
    expect(pipe).toHaveBeenCalledTimes(1);

    store.clearSelection();
    const empty = store.getSelection();
    store.clearSelection();
    expect(store.getSelection()).toBe(empty);
    expect(empty).toEqual({ cardIds: new Set(), pipeIds: new Set() });
    expect(pipe).toHaveLastReturnedWith(false);
    expect(selection).toHaveBeenCalledTimes(3);
    expect(a).toHaveBeenCalledTimes(2);
    expect(c).toHaveBeenCalledTimes(0);
    expect(store.getCardState("c")).toBe(untouchedCard);
  });

  it.each([
    ["setHoveredCard", "hovered"],
    ["setResizingCard", "resizing"],
  ] as const)(
    "%s notifies just the card losing and gaining the state",
    (setter, flag) => {
      const store = createCellInteractionStore();
      const a = vi.fn(() => store.getCardState("a")[flag]);
      const b = vi.fn(() => store.getCardState("b")[flag]);
      const c = vi.fn();
      const unsubscribeA = store.subscribeCard("a", a);
      store.subscribeCard("b", b);
      store.subscribeCard("c", c);

      store[setter]("a");
      expect(a).toHaveLastReturnedWith(true);
      store[setter]("a");
      store[setter]("b");
      expect(a).toHaveBeenCalledTimes(2);
      expect(a).toHaveLastReturnedWith(false);
      expect(b).toHaveLastReturnedWith(true);
      expect(c).toHaveBeenCalledTimes(0);
      unsubscribeA();
      store[setter]("a");
      expect(a).toHaveBeenCalledTimes(2);
      expect(b).toHaveLastReturnedWith(false);
      expect(store.getCardState("a")[flag]).toBe(true);
    },
  );

  it("keeps snapshots for cards that stay in the drag and for pipes that stay unhovered", () => {
    const store = createCellInteractionStore();
    const a = vi.fn(() => store.getCardState("a").dragging);
    const b = vi.fn(() => store.getCardState("b").dragging);
    const c = vi.fn(() => store.getCardState("c").dragging);
    const pipe = vi.fn(() => store.getPipeState("pipe").hovered);
    store.subscribeCard("a", a);
    store.subscribeCard("b", b);
    store.subscribeCard("c", c);
    const unsubscribePipe = store.subscribePipe("pipe", pipe);
    const otherPipe = store.getPipeState("other");

    store.setDraggingCards(["a", "b"]);
    const draggingB = store.getCardState("b");
    store.setDraggingCards(["b", "c"]);
    expect(a).toHaveLastReturnedWith(false);
    expect(b).toHaveBeenCalledTimes(1);
    expect(b).toHaveLastReturnedWith(true);
    expect(c).toHaveLastReturnedWith(true);
    expect(store.getCardState("b")).toBe(draggingB);

    store.setHoveredPipe("pipe");
    expect(pipe).toHaveLastReturnedWith(true);
    const hoveredPipe = store.getPipeState("pipe");
    store.setHoveredPipe("pipe");
    expect(store.getPipeState("pipe")).toBe(hoveredPipe);
    expect(pipe).toHaveBeenCalledTimes(1);
    expect(store.getPipeState("other")).toBe(otherPipe);
    unsubscribePipe();
    store.setHoveredPipe(null);
    expect(store.getPipeState("pipe").hovered).toBe(false);
    expect(pipe).toHaveBeenCalledTimes(1);
  });

  it("publishes remote cursor moves only to peer listeners and preserves equal badges", () => {
    const store = createCellInteractionStore();
    const first: CellRemotePeerState = {
      actorId: "ada",
      displayName: "Ada",
      color: "blue",
      cursor: null,
      selectedCardIds: ["a"],
      draggingCards: { a: { col: 2, row: 3 } },
    };
    const second: CellRemotePeerState = {
      actorId: "jo",
      displayName: "Jo",
      color: "green",
      cursor: null,
      selectedCardIds: ["b"],
      draggingCards: { a: { col: 8, row: 9 } },
    };
    const a = vi.fn();
    const b = vi.fn();
    const peers = vi.fn(() => store.getRemotePeers());
    store.subscribeCard("a", a);
    store.subscribeCard("b", b);
    store.subscribeRemotePeers(peers);
    expect(store.getCardState("a").remoteSelectedBy).toBe(EMPTY_REMOTE_BADGES);
    expect(Object.isFrozen(EMPTY_REMOTE_BADGES)).toBe(true);

    store.setRemotePeers([first, second]);
    const initial = store.getCardState("a");
    expect(initial.remoteSelectedBy).toEqual([
      { actorId: "ada", displayName: "Ada", color: "blue" },
    ]);
    expect(initial.remoteDragCell).toEqual({ col: 2, row: 3 });
    expect(initial.remoteDragColor).toBe("blue");

    const cursor = {
      ...first,
      cursor: { x: 10, y: 12 },
      draggingCards: { a: { col: 2, row: 3 } },
    };
    store.setRemotePeers([cursor, second]);
    expect(peers).toHaveBeenCalledTimes(2);
    expect(peers).toHaveLastReturnedWith([cursor, second]);
    expect(a).toHaveBeenCalledTimes(1);
    expect(b).toHaveBeenCalledTimes(1);
    expect(store.getCardState("a")).toBe(initial);

    store.setRemotePeers([{ ...cursor, draggingCards: {} }, second]);
    const handoff = store.getCardState("a");
    expect(a).toHaveBeenCalledTimes(2);
    expect(b).toHaveBeenCalledTimes(1);
    expect(handoff.remoteDragCell).toEqual({ col: 8, row: 9 });
    expect(handoff.remoteDragColor).toBe("green");
    expect(handoff.remoteSelectedBy).toBe(initial.remoteSelectedBy);

    store.setRemotePeers([
      { ...first, displayName: "Ada L.", draggingCards: {} },
      second,
    ]);
    expect(a).toHaveBeenCalledTimes(3);
    expect(store.getCardState("a").remoteSelectedBy).toEqual([
      { actorId: "ada", displayName: "Ada L.", color: "blue" },
    ]);
    store.setRemotePeers([]);
    expect(a).toHaveBeenCalledTimes(4);
    expect(b).toHaveBeenCalledTimes(2);
    expect(store.getCardState("a")).toMatchObject({
      remoteDragCell: null,
      remoteDragColor: null,
    });
    expect(store.getCardState("a").remoteSelectedBy).toBe(EMPTY_REMOTE_BADGES);
  });

  it("deduplicates marquee coordinates and active port keys independently", () => {
    const store = createCellInteractionStore();
    const marquee = vi.fn(() => store.getMarquee());
    const active = vi.fn(() => store.getActivePortKey());
    store.subscribeMarquee(marquee);
    store.subscribeActivePort(active);

    const rect = { start: { x: 1, y: 2 }, current: { x: 3, y: 4 } };
    store.setMarquee(rect);
    const snapshot = store.getMarquee();
    store.setMarquee({
      start: { ...rect.start },
      current: { ...rect.current },
    });
    expect(marquee).toHaveBeenCalledTimes(1);
    expect(store.getMarquee()).toBe(snapshot);
    store.setActivePortKey("a:out");
    store.setActivePortKey("a:out");
    expect(active).toHaveBeenCalledTimes(1);
    expect(active).toHaveLastReturnedWith("a:out");
    store.setMarquee(null);
    store.setActivePortKey(null);
    expect(marquee).toHaveBeenCalledTimes(2);
    expect(marquee).toHaveLastReturnedWith(null);
    expect(active).toHaveBeenCalledTimes(2);
    expect(active).toHaveLastReturnedWith(null);
  });
});

describe("marquee hit testing", () => {
  it("normalizes a reverse gesture and distinguishes intersecting and contained cards", () => {
    const card: CellCardModel = {
      id: "inside",
      title: "Card",
      subtitle: "",
      ports: [],
      col: 0,
      row: 0,
      widthCells: 6,
      heightCells: 4,
    };
    const cards = [
      card,
      { ...card, id: "partial", col: -4 },
      { ...card, id: "outside", row: 8 },
    ];
    const rect = { start: { x: 150, y: 100 }, current: { x: -20, y: -10 } };
    expect(normalizeMarqueeRect(rect)).toEqual({
      x: -20,
      y: -10,
      width: 170,
      height: 110,
    });
    expect(cardsInMarqueeRect(cards, rect)).toEqual(["inside", "partial"]);
    expect(cardsInMarqueeRect(cards, rect, "contain")).toEqual(["inside"]);
  });

  it("finds segments crossing the box from outside and excludes a diagonal near miss", () => {
    function route(id: string, ...points: WorldPoint[]): RoutedCellPipe {
      return {
        id,
        points,
        cellPath: [],
        sourceExit: "right",
        targetExit: "left",
        depth: 0,
      };
    }
    const routes = [
      route("horizontal", { x: 30, y: 15 }, { x: 0, y: 15 }),
      route("vertical", { x: 0, y: 0 }, { x: 10, y: 0 }, { x: 10, y: 30 }),
      route("diagonal", { x: 0, y: 0 }, { x: 30, y: 30 }),
      route("near miss", { x: 0, y: 23 }, { x: 13, y: 31 }),
      route("parallel outside", { x: 0, y: 9 }, { x: 30, y: 9 }),
    ];
    const rect = { start: { x: 20, y: 25 }, current: { x: 10, y: 10 } };
    expect(
      pipesInMarqueeRect(new Map(routes.map((pipe) => [pipe.id, pipe])), rect),
    ).toEqual(["horizontal", "vertical", "diagonal"]);
  });
});
